from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog, LedgerAccount, OutboxEvent, User, WalletAccount, utcnow


async def enqueue_message(session: AsyncSession, chat_id: int, text: str, *, event_type: str = "send_message") -> None:
    session.add(OutboxEvent(event_type=event_type, payload={"chat_id": chat_id, "text": text}))


async def audit(
    session: AsyncSession, actor_id: int | None, action: str,
    entity_type: str, entity_id: str | int, metadata: dict[str, Any] | None = None,
) -> None:
    session.add(AuditLog(
        actor_telegram_id=actor_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id), metadata_json=metadata or {},
    ))


async def ensure_user_wallet(session: AsyncSession, user_id: int, currency: str) -> WalletAccount:
    wallet = await session.scalar(select(WalletAccount).where(WalletAccount.user_id == user_id).with_for_update())
    if wallet is None:
        wallet = WalletAccount(user_id=user_id, currency=currency, balance_minor=0)
        session.add(wallet)
        await session.flush()
    return wallet


async def ensure_ledger_account(
    session: AsyncSession, account_code: str, account_type: str, currency: str,
    user_id: int | None = None,
) -> LedgerAccount:
    account = await session.scalar(
        select(LedgerAccount).where(
            LedgerAccount.account_code == account_code,
            LedgerAccount.currency == currency,
        ).with_for_update()
    )
    if account is None:
        account = LedgerAccount(
            account_code=account_code, account_type=account_type,
            currency=currency, user_id=user_id,
        )
        session.add(account)
        await session.flush()
    return account
