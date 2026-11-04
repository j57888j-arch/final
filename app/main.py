from __future__ import annotations

import asyncio
import logging

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.core.logging import configure_logging
from app.core.monitoring import initialize_monitoring
from app.database.init import initialize_database
from app.database.session import dispose_engine
from app.workers.outbox import run_outbox_worker


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_monitoring(settings)
    if settings.webhook_url:
        raise RuntimeError("WEBHOOK_URL sozlangan. Polling uchun WEBHOOK_URL ni bo‘sh qoldiring.")
    await initialize_database(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)
    worker = asyncio.create_task(run_outbox_worker(bot, settings))
    try:
        await dispatcher.start_polling(bot, settings=settings, allowed_updates=sorted(set(dispatcher.resolve_used_update_types()) | {"pre_checkout_query"}))
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        try:
            await dispatcher.storage.close()
        except Exception:
            pass
        redis_client = getattr(dispatcher, "_rate_limit_redis", None)
        if redis_client:
            await redis_client.aclose()
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
