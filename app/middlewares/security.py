from __future__ import annotations

import time
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.database.session import SessionFactory
from app.services.admin_service import has_permission, is_admin
from app.database.models import User
from sqlalchemy import select

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, redis_client=None, *, limit: int = 8, window_seconds: int = 5) -> None:
        self.redis = redis_client
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[int, list[float]] = defaultdict(list)

    async def __call__(
        self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery, data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        allowed = True
        if self.redis is not None:
            try:
                key = f"weraqambot:rl:{user.id}"
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, self.window_seconds)
                allowed = count <= self.limit
            except Exception:
                logger.warning("Redis rate limit unavailable; using local fallback", exc_info=True)
                self.redis = None
        if self.redis is None:
            now = time.monotonic()
            bucket = [t for t in self._buckets[user.id] if now - t < self.window_seconds]
            bucket.append(now)
            self._buckets[user.id] = bucket
            allowed = len(bucket) <= self.limit
        if not allowed:
            if isinstance(event, CallbackQuery):
                await event.answer("Juda tez yuboryapsiz. Biroz kuting.")
            else:
                await event.answer("Juda tez yuboryapsiz. Biroz kuting.")
            return None
        return await handler(event, data)


class AdminStateGuardMiddleware(BaseMiddleware):
    """Re-check DB role permissions for multi-step admin FSM conversations."""

    STATE_PERMISSIONS = {
        "AdminCountryStates": "catalog.manage",
        "AdminServiceStates": "catalog.manage",
        "AdminEditServiceStates": "catalog.manage",
        "AdminStockStates": "inventory.manage",
        "AdminInventoryImportStates": "inventory.manage",
        "AdminBroadcastStates": "broadcast.create",
        "AdminSearchStates": "users.manage",
        "AdminPromoStates": "catalog.manage",
    }

    async def __call__(
        self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery, data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        current = await state.get_state() if state else None
        if current:
            state_prefix = current.split(":", 1)[0]
            permission = self.STATE_PERMISSIONS.get(state_prefix)
            user = getattr(event, "from_user", None)
            settings = data.get("settings")
            if permission and user and settings:
                async with SessionFactory() as session:
                    allowed = await has_permission(session, user.id, permission, settings.admin_ids)
                    admin = await is_admin(session, user.id, settings.admin_ids)
                if not allowed or not admin:
                    await state.clear()
                    if isinstance(event, CallbackQuery):
                        await event.answer("Admin ruxsati bekor qilingan.", show_alert=True)
                    else:
                        await event.answer("⛔ Bu amal uchun ruxsatingiz yo‘q. Suhbat bekor qilindi.")
                    return None
        return await handler(event, data)


class UserBlockMiddleware(BaseMiddleware):
    """Stop blocked customers from using existing sessions or callback buttons."""

    async def __call__(
        self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery, data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        # Let /start reach the handler so it can display the restriction notice.
        message_text = (event.text or "") if isinstance(event, Message) else ""
        command = message_text.split(maxsplit=1)[0] if message_text else ""
        if command == "/start" or command.startswith("/start@"):
            return await handler(event, data)
        if isinstance(event, Message) and event.successful_payment is not None:
            # A payment already accepted by Telegram must still be recorded, even if
            # an administrator blocked the customer between pre-checkout and payment.
            return await handler(event, data)
        now = datetime.now(timezone.utc)
        async with SessionFactory() as session:
            async with session.begin():
                customer = await session.scalar(
                    select(User).where(User.telegram_id == user.id)
                )
                is_blocked = bool(customer.is_blocked) if customer else False
                # Update meaningful activity at most once every five minutes to
                # keep the 30-day dashboard metric accurate without writing on
                # every single button press.
                if customer and not is_blocked:
                    last_activity = customer.last_activity_at
                    if last_activity is not None and last_activity.tzinfo is None:
                        last_activity = last_activity.replace(tzinfo=timezone.utc)
                    if last_activity is None or now - last_activity >= timedelta(minutes=5):
                        customer.last_activity_at = now
        if is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Hisobingiz cheklangan. Support bilan bog‘laning.", show_alert=True)
            else:
                await event.answer("⛔ Hisobingiz cheklangan. Support bilan bog‘laning.")
            return None
        return await handler(event, data)
