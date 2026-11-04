from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LedgerEntry, WalletTransaction
from app.services.common import ensure_ledger_account, ensure_user_wallet


class WalletError(Exception):
    pass


async def post_wallet_transaction(
    session: AsyncSession,
    *,
    user_id: int,
    amount_minor: int,
    currency: str,
    transaction_type: str,
    idempotency_key: str,
    direction: str,
    reference_type: str = "",
    reference_id: int | None = None,
    description: str = "",
) -> bool:
    """Post a balanced double-entry transaction. Caller owns the DB transaction."""
    if amount_minor <= 0:
        raise WalletError("Transaction amount must be positive")
    existing = await session.scalar(
        select(WalletTransaction).where(WalletTransaction.idempotency_key == idempotency_key)
    )
    if existing:
        return False

    wallet = await ensure_user_wallet(session, user_id, currency)
    if wallet.currency != currency:
        raise WalletError(f"Wallet currency mismatch: {wallet.currency} != {currency}")
    user_account = await ensure_ledger_account(
        session, f"USER_WALLET:{user_id}", "liability", currency, user_id
    )

    if direction == "credit":
        wallet.balance_minor += amount_minor
        counterpart = await ensure_ledger_account(session, f"SYSTEM_CASH:{currency}", "asset", currency)
        debit_account, credit_account = counterpart, user_account
    elif direction == "debit":
        if wallet.balance_minor < amount_minor:
            raise WalletError("Balans yetarli emas")
        wallet.balance_minor -= amount_minor
        counterpart = await ensure_ledger_account(session, f"SYSTEM_REVENUE:{currency}", "revenue", currency)
        debit_account, credit_account = user_account, counterpart
    elif direction == "refund":
        wallet.balance_minor += amount_minor
        counterpart = await ensure_ledger_account(session, f"SYSTEM_REVENUE:{currency}", "revenue", currency)
        debit_account, credit_account = counterpart, user_account
    elif direction == "adjust_debit":
        if wallet.balance_minor < amount_minor:
            raise WalletError("Balans yetarli emas")
        wallet.balance_minor -= amount_minor
        counterpart = await ensure_ledger_account(session, f"SYSTEM_ADJUSTMENT:{currency}", "equity", currency)
        debit_account, credit_account = user_account, counterpart
    else:
        raise WalletError("Noma’lum wallet yo‘nalishi")

    tx = WalletTransaction(
        idempotency_key=idempotency_key, user_id=user_id,
        transaction_type=transaction_type, amount_minor=amount_minor,
        currency=currency, reference_type=reference_type,
        reference_id=reference_id, description=description,
    )
    session.add(tx)
    await session.flush()
    session.add_all([
        LedgerEntry(transaction_id=tx.id, account_id=debit_account.id, debit_minor=amount_minor, credit_minor=0),
        LedgerEntry(transaction_id=tx.id, account_id=credit_account.id, debit_minor=0, credit_minor=amount_minor),
    ])
    return True
