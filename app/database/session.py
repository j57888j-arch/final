from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine_kwargs = {"pool_pre_ping": True}
if settings.async_database_url.startswith("postgresql"):
    engine_kwargs.update(pool_size=5, max_overflow=10, pool_recycle=1800)
engine = create_async_engine(settings.async_database_url, **engine_kwargs)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with SessionFactory() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
