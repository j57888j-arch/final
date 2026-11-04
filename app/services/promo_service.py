from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PromoCode
from app.services.common import audit


async def create_promo(
    session: AsyncSession, *, code: str, discount_type: str, discount_value: int,
    max_uses: int | None, per_user_limit: int, min_order_minor: int,
    expires_in_days: int | None, created_by: int,
) -> PromoCode:
    code = code.strip().upper()
    if not code or len(code) > 48:
        raise ValueError("Promo-kod 1–48 belgidan iborat bo‘lishi kerak.")
    if discount_type not in {"percent", "fixed"} or discount_value <= 0:
        raise ValueError("Chegirma turi yoki qiymati noto‘g‘ri.")
    if discount_type == "percent" and discount_value > 100:
        raise ValueError("Foizli chegirma 100 dan oshmasligi kerak.")
    if per_user_limit < 1 or (max_uses is not None and max_uses < 1):
        raise ValueError("Foydalanish limiti noto‘g‘ri.")
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days) if expires_in_days else None
    promo = PromoCode(
        code=code, discount_type=discount_type, discount_value=discount_value,
        max_uses=max_uses, per_user_limit=per_user_limit,
        min_order_minor=min_order_minor, expires_at=expires_at,
        is_active=True, created_by=created_by,
    )
    session.add(promo)
    await session.flush()
    await audit(session, created_by, "promo.created", "promo_code", promo.id,
                {"code": promo.code, "discount_type": discount_type, "discount_value": discount_value})
    return promo
