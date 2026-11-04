from __future__ import annotations

from sqlalchemy import text

from app.config import Settings
from app.database.base import Base
from app.database.session import SessionFactory, engine


async def initialize_database(settings: Settings) -> None:
    # Import all models so SQLAlchemy metadata is complete before migrations/create_all.
    from app.database import models  # noqa: F401

    if settings.auto_create_tables:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(text("SELECT 1"))
            from app.services.admin_service import ensure_bootstrap_admins
            await ensure_bootstrap_admins(session, settings.admin_ids)
