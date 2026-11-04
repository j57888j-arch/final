from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, User


async def dashboard(session: AsyncSession, currency: str = "UZS") -> dict[str, int]:
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo("Asia/Tashkent"))
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = local_midnight.astimezone(timezone.utc)
    month_start_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start_local.astimezone(timezone.utc)
    return {
        "users": int(await session.scalar(select(func.count(User.id))) or 0),
        "new_users_today": int(await session.scalar(select(func.count(User.id)).where(User.created_at >= today)) or 0),
        "active_users_30d": int(await session.scalar(select(func.count(User.id)).where(User.last_activity_at >= now - timedelta(days=30))) or 0),
        "orders": int(await session.scalar(select(func.count(Order.id))) or 0),
        "orders_today": int(await session.scalar(select(func.count(Order.id)).where(Order.created_at >= today)) or 0),
        "completed": int(await session.scalar(select(func.count(Order.id)).where(Order.status == "completed")) or 0),
        "pending": int(await session.scalar(select(func.count(Order.id)).where(Order.status.in_(["paid", "processing", "awaiting_payment"]))) or 0),
        "payments_total": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.currency == currency.upper())) or 0),
        "payments_today": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.currency == currency.upper(), Payment.created_at >= today)) or 0),
        "payments_month": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.currency == currency.upper(), Payment.created_at >= month_start)) or 0),
        "stars_total": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.provider == "telegram_stars", Payment.currency == "XTR")) or 0),
        "manual_total": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.provider == "manual", Payment.currency == currency.upper())) or 0),
        "click_total": int(await session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid", Payment.provider == "click", Payment.currency == currency.upper())) or 0),
        "cancelled": int(await session.scalar(select(func.count(Order.id)).where(Order.status.in_(["cancelled", "rejected", "refunded"]))) or 0),
        "week_orders": int(await session.scalar(select(func.count(Order.id)).where(Order.created_at >= now - timedelta(days=7))) or 0),
    }
