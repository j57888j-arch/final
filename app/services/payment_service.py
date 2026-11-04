from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import Payment, PaymentProof, User
from app.services.common import audit, enqueue_message
from app.services.wallet_service import post_wallet_transaction


class PaymentError(Exception):
    pass


async def create_manual_topup(
    session: AsyncSession, *, user: User, amount_minor: int, settings: Settings,
) -> Payment:
    if settings.payment_mode != "manual":
        raise PaymentError("Qo‘lda to‘lov hozircha o‘chirilgan.")
    if not settings.payment_card_number:
        raise PaymentError("To‘lov rekvizitlari hali sozlanmagan. Administratorga murojaat qiling.")
    if amount_minor < settings.money_scale or amount_minor > 100_000_000 * settings.money_scale:
        raise PaymentError("To‘lov summasi ruxsat etilgan oraliqda emas.")
    payment = Payment(
        user_id=user.id, provider="manual", amount_minor=amount_minor,
        currency=settings.default_currency, status="pending",
        payload=f"manual:{user.id}:{secrets.token_urlsafe(12)}",
    )
    session.add(payment)
    await session.flush()
    return payment


async def attach_payment_proof(session: AsyncSession, *, payment_id: int, user_id: int, file_id: str) -> Payment:
    payment = await session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment or payment.user_id != user_id or payment.provider != "manual" or payment.status != "pending":
        raise PaymentError("Tekshirish uchun faol to‘lov topilmadi.")
    payment.proof_file_id = file_id
    session.add(PaymentProof(
        payment_id=payment.id, telegram_file_id=file_id,
        uploaded_by=(await session.get(User, user_id)).telegram_id,
        review_status="pending",
    ))
    return payment


async def approve_manual_payment(
    session: AsyncSession, *, payment_id: int, admin_telegram_id: int,
) -> Payment:
    payment = await session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment or payment.provider != "manual" or payment.status != "pending" or not payment.proof_file_id:
        raise PaymentError("To‘lov topilmadi yoki chek hali yuborilmagan.")
    payment.status = "paid"
    payment.reviewed_by = admin_telegram_id
    proofs = (await session.scalars(select(PaymentProof).where(PaymentProof.payment_id == payment.id).with_for_update())).all()
    for proof in proofs:
        proof.review_status = "approved"
        proof.reviewed_by = admin_telegram_id
        proof.reviewed_at = datetime.now(timezone.utc)
    payment.reviewed_at = datetime.now(timezone.utc)
    await post_wallet_transaction(
        session, user_id=payment.user_id, amount_minor=payment.amount_minor,
        currency=payment.currency, transaction_type="credit",
        idempotency_key=f"payment:{payment.id}:credit", direction="credit",
        reference_type="payment", reference_id=payment.id,
        description=f"To‘lov #{payment.id} tasdiqlandi",
    )
    user = await session.get(User, payment.user_id)
    if user:
        await enqueue_message(session, user.telegram_id, f"✅ #{payment.id} to‘lovingiz tasdiqlandi. Balansingiz to‘ldirildi.")
    await audit(session, admin_telegram_id, "payment.approved", "payment", payment.id, {"amount_minor": payment.amount_minor})
    return payment


async def reject_manual_payment(
    session: AsyncSession, *, payment_id: int, admin_telegram_id: int, reason: str = "",
) -> Payment:
    payment = await session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment or payment.provider != "manual" or payment.status != "pending":
        raise PaymentError("To‘lov topilmadi yoki oldin ko‘rib chiqilgan.")
    payment.status = "rejected"
    payment.reviewed_by = admin_telegram_id
    proofs = (await session.scalars(select(PaymentProof).where(PaymentProof.payment_id == payment.id).with_for_update())).all()
    for proof in proofs:
        proof.review_status = "rejected"
        proof.reviewed_by = admin_telegram_id
        proof.reviewed_at = datetime.now(timezone.utc)
    payment.reviewed_at = datetime.now(timezone.utc)
    payment.rejection_reason = reason[:500]
    user = await session.get(User, payment.user_id)
    if user:
        await enqueue_message(session, user.telegram_id, f"⚠️ #{payment.id} to‘lovingiz rad etildi. Sabab: {reason or 'Chek tasdiqlanmadi'}")
    await audit(session, admin_telegram_id, "payment.rejected", "payment", payment.id, {"reason": reason[:200]})
    return payment


async def get_payment_by_payload(session: AsyncSession, payload: str) -> Payment | None:
    return await session.scalar(select(Payment).where(Payment.payload == payload))
