from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import Referral, User, WalletAccount


def _referral_code() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12].upper()


async def register_user(
    session: AsyncSession, *, telegram_id: int, username: str | None,
    first_name: str, last_name: str, referral_code: str | None, settings: Settings,
) -> tuple[User, bool]:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
    if user:
        user.username = username
        user.first_name = first_name or ""
        user.last_name = last_name or ""
        user.full_name = " ".join(x for x in [first_name, last_name] if x).strip()
        user.last_activity_at = datetime.now(timezone.utc)
        if not await session.scalar(select(WalletAccount.id).where(WalletAccount.user_id == user.id)):
            session.add(WalletAccount(user_id=user.id, currency=settings.default_currency, balance_minor=0))
        return user, False

    referrer = None
    if referral_code:
        referrer = await session.scalar(select(User).where(User.referral_code == referral_code.upper()))
        if referrer and referrer.telegram_id == telegram_id:
            referrer = None

    user = User(
        telegram_id=telegram_id, username=username, first_name=first_name or "",
        last_name=last_name or "", full_name=" ".join(x for x in [first_name, last_name] if x).strip(),
        referral_code=_referral_code(), referred_by_id=referrer.id if referrer else None,
    )
    session.add(user)
    await session.flush()
    session.add(WalletAccount(user_id=user.id, currency=settings.default_currency, balance_minor=0))
    if referrer:
        session.add(Referral(
            referrer_user_id=referrer.id, referred_user_id=user.id,
            status="pending", bonus_minor=settings.referral_bonus_minor,
        ))
    return user, True


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_wallet_balance(session: AsyncSession, user_id: int) -> int:
    return int(await session.scalar(select(WalletAccount.balance_minor).where(WalletAccount.user_id == user_id)) or 0)


async def count_user_orders(session: AsyncSession, user_id: int) -> int:
    from app.database.models import Order
    return int(await session.scalar(select(func.count(Order.id)).where(Order.user_id == user_id)) or 0)
