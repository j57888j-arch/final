from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.database.init import initialize_database
from app.database.session import SessionFactory, dispose_engine
from app.core.security import verify_webhook_secret
from app.core.logging import configure_logging
from app.core.monitoring import initialize_monitoring

logger = logging.getLogger(__name__)
settings = get_settings()
bot = None
dispatcher = None


configure_logging(settings.log_level)
initialize_monitoring(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, dispatcher
    await initialize_database(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)
    if settings.is_production and not settings.webhook_url:
        raise RuntimeError("Production web service uchun WEBHOOK_URL sozlanishi kerak.")
    if settings.webhook_url:
        webhook_secret = settings.webhook_secret.get_secret_value()
        if settings.is_production and not webhook_secret:
            raise RuntimeError("Production webhook uchun WEBHOOK_SECRET majburiy.")
        await bot.set_webhook(
            url=f"{settings.webhook_url.rstrip('/')}/telegram/webhook",
            secret_token=webhook_secret or None,
            allowed_updates=sorted(set(dispatcher.resolve_used_update_types()) | {"pre_checkout_query"}),
            drop_pending_updates=False,
        )
    try:
        yield
    finally:
        if dispatcher:
            try:
                await dispatcher.storage.close()
            except Exception:
                logger.exception("Failed to close FSM storage")
            redis_client = getattr(dispatcher, "_rate_limit_redis", None)
            if redis_client:
                try:
                    await redis_client.aclose()
                except Exception:
                    logger.exception("Failed to close Redis rate-limit client")
        if bot:
            if settings.webhook_url:
                try:
                    await bot.delete_webhook(drop_pending_updates=False)
                except Exception:
                    logger.exception("Failed to delete webhook")
            await bot.session.close()
        await dispose_engine()


app = FastAPI(title="WeraqamBot V2", version="2.1.0", lifespan=lifespan)

from app.api.click_webhook import router as click_router
app.include_router(click_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "weraqambot"}


@app.get("/readyz")
async def readyz():
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        if settings.redis_url:
            from redis.asyncio import Redis
            client = Redis.from_url(settings.redis_url)
            await client.ping()
            await client.aclose()
        return {"status": "ready"}
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Dependencies are not ready") from exc


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if bot is None or dispatcher is None:
        raise HTTPException(status_code=503, detail="Bot is starting")
    expected = settings.webhook_secret.get_secret_value()
    if expected and not verify_webhook_secret(expected, x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    if settings.is_production and not expected:
        raise HTTPException(status_code=403, detail="Webhook secret is required")
    try:
        body = await request.json()
        update = Update.model_validate(body, context={"bot": bot})
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Telegram update payload") from exc
    try:
        await dispatcher.feed_update(bot, update, settings=settings)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Webhook update processing failed")
        # Non-2xx lets Telegram retry delivery after transient application errors.
        raise HTTPException(status_code=500, detail="Update processing failed") from exc
