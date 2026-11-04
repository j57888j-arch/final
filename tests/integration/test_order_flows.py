from __future__ import annotations

import pytest

pytest.importorskip("aiosqlite", reason="aiosqlite is installed from requirements.txt for async SQLite integration tests")
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.base import Base
from app.database.models import (
    AdminUser, Country, Inventory, LedgerEntry, Order, Payment, PromoCode,
    PromoRedemption, Service, User, WalletAccount, WalletTransaction,
)
from app.services.catalog_service import create_service
from app.services.order_service import (
    claim_order, complete_order, create_stars_order, create_wallet_order,
    settle_stars_payment,
)
from app.services.wallet_service import post_wallet_transaction


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_user_and_country(session):
    user = User(
        telegram_id=10001, first_name="Test", last_name="User", full_name="Test User",
        referral_code="TESTUSER01",
    )
    admin_user = User(
        telegram_id=20002, first_name="Admin", last_name="User", full_name="Admin User",
        referral_code="ADMINUSER01",
    )
    country = Country(name="Uzbekistan", emoji="🇺🇿", description="")
    session.add_all([user, admin_user, country])
    await session.flush()
    session.add(WalletAccount(user_id=user.id, balance_minor=0, currency="UZS"))
    await session.flush()
    return user, admin_user, country


@pytest.mark.asyncio
async def test_wallet_order_reserves_stock_and_completes_atomically(db_session):
    settings = Settings()
    async with db_session.begin():
        user, admin_user, country = await _seed_user_and_country(db_session)
        service = await create_service(
            db_session, country_id=country.id, name="Voice routing", description="Lawful service",
            price_minor=250_000, currency="UZS", initial_stock=2,
            stars_price=None, is_digital=False,
        )
        await post_wallet_transaction(
            db_session, user_id=user.id, amount_minor=500_000, currency="UZS",
            transaction_type="credit", idempotency_key="test:wallet:funding",
            direction="credit", reference_type="test", reference_id=1,
            description="Test funding",
        )
        order = await create_wallet_order(
            db_session, user=user, service_id=service.id, quantity=1,
            promo_code=None, settings=settings,
        )
        order_id = order.id
        inventory = await db_session.scalar(select(Inventory).where(Inventory.service_id == service.id))
        wallet = await db_session.scalar(select(WalletAccount).where(WalletAccount.user_id == user.id))
        assert (inventory.available_quantity, inventory.reserved_quantity, inventory.sold_quantity) == (1, 1, 0)
        assert wallet.balance_minor == 250_000

        await claim_order(
            db_session, order_id=order.id, admin_telegram_id=admin_user.telegram_id,
            bootstrap_ids={admin_user.telegram_id},
        )
        await complete_order(db_session, order_id=order.id, admin_telegram_id=admin_user.telegram_id)

        await db_session.refresh(order)
        await db_session.refresh(inventory)
        assert order.status == "completed"
        assert (inventory.available_quantity, inventory.reserved_quantity, inventory.sold_quantity) == (1, 0, 1)
        assert inventory.total_quantity == 2

    async with db_session.begin():
        wallet = await db_session.scalar(select(WalletAccount).where(WalletAccount.user_id == user.id))
        txs = (await db_session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id))).all()
        entries = (await db_session.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id.in_([t.id for t in txs])))).all()
        assert wallet.balance_minor == 250_000
        assert len(txs) == 2
        assert sum(x.debit_minor for x in entries) == sum(x.credit_minor for x in entries)
        # Replaying a ledger request with the same idempotency key is a no-op.
        applied = await post_wallet_transaction(
            db_session, user_id=user.id, amount_minor=500_000, currency="UZS",
            transaction_type="credit", idempotency_key="test:wallet:funding",
            direction="credit", reference_type="test", reference_id=1,
            description="Duplicate funding",
        )
        assert applied is False
        await db_session.refresh(wallet)
        assert wallet.balance_minor == 250_000


@pytest.mark.asyncio
async def test_stars_payment_settles_order_and_promo_reservation(db_session):
    settings = Settings(telegram_stars_enabled=True, payment_expiration_minutes=30)
    async with db_session.begin():
        user, _, country = await _seed_user_and_country(db_session)
        service = await create_service(
            db_session, country_id=country.id, name="Digital support pack", description="Stars-only product",
            price_minor=100_000, currency="UZS", initial_stock=3,
            stars_price=20, is_digital=True,
        )
        promo = PromoCode(
            code="SAVE10", discount_type="percent", discount_value=10,
            max_uses=1, per_user_limit=1, min_order_minor=0,
            is_active=True, created_by=20002,
        )
        db_session.add(promo)
        await db_session.flush()
        order, payment = await create_stars_order(
            db_session, user=user, service_id=service.id, quantity=1,
            promo_code="SAVE10", settings=settings,
        )
        payload = payment.payload
        order_id = order.id
        payment_id = payment.id
        # Once Telegram accepts pre-checkout, successful_payment may arrive later
        # than the local checkout reservation expiry; the charge is still authoritative.
        from datetime import datetime, timedelta, timezone
        order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert payment.amount_minor == 18
        redemption = await db_session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id))
        assert redemption.status == "reserved"

    async with db_session.begin():
        payment, order = await settle_stars_payment(
            db_session, payload=payload, telegram_charge_id="tg-charge-123",
            user_telegram_id=10001, paid_amount=18, currency="XTR",
        )
        assert order.id == order_id
        assert payment.id == payment_id
        assert payment.status == "paid"
        assert order.status == "paid"
        redemption = await db_session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order_id))
        assert redemption.status == "applied"

    async with db_session.begin():
        # A duplicate successful_payment update is idempotent.
        payment, order = await settle_stars_payment(
            db_session, payload=payload, telegram_charge_id="tg-charge-123",
            user_telegram_id=10001, paid_amount=18, currency="XTR",
        )
        assert payment.status == "paid"
        assert order.status == "paid"
        inventory = await db_session.scalar(select(Inventory).where(Inventory.service_id == 1))
        assert inventory.reserved_quantity == 1
        payments = (await db_session.scalars(select(Payment).where(Payment.id == payment_id))).all()
        assert len(payments) == 1
