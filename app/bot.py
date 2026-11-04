from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.middlewares.security import AdminStateGuardMiddleware, RateLimitMiddleware, UserBlockMiddleware

from app.config import Settings
from app.handlers.admin import router as admin_router
from app.handlers.fallback import router as fallback_router
from app.handlers.user import router as user_router


def create_bot(settings: Settings) -> Bot:
    token = settings.bot_token.get_secret_value().strip()
    if not token or ":" not in token:
        raise RuntimeError("BOT_TOKEN .env faylida to‘g‘ri sozlanmagan.")
    return Bot(token=token, default=DefaultBotProperties(parse_mode=None))


def create_dispatcher(settings: Settings) -> Dispatcher:
    redis_client = None
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage
        from redis.asyncio import Redis
        storage = RedisStorage.from_url(settings.redis_url)
        redis_client = Redis.from_url(settings.redis_url)
    else:
        if settings.is_production:
            raise RuntimeError("Production muhitida REDIS_URL majburiy.")
        storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(user_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(fallback_router)
    dispatcher["settings"] = settings
    dispatcher["rate_limit_redis"] = redis_client
    dispatcher._rate_limit_redis = redis_client
    dispatcher.message.outer_middleware(RateLimitMiddleware(redis_client))
    dispatcher.callback_query.outer_middleware(RateLimitMiddleware(redis_client))
    dispatcher.message.outer_middleware(UserBlockMiddleware())
    dispatcher.callback_query.outer_middleware(UserBlockMiddleware())
    dispatcher.message.outer_middleware(AdminStateGuardMiddleware())
    return dispatcher
