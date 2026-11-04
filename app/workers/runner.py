from __future__ import annotations

import asyncio
import logging

from app.bot import create_bot
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
    while True:
        try:
            await initialize_database(settings)
            break
        except Exception:
            logging.getLogger(__name__).exception(
                "Database is not ready yet (the web service may still be applying Alembic migrations); retrying in 10 seconds"
            )
            await asyncio.sleep(10)
    bot = create_bot(settings)
    try:
        await run_outbox_worker(bot, settings)
    finally:
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
