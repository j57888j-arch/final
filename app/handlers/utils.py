from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.session import SessionFactory
from app.services.user_service import register_user


@asynccontextmanager
async def session_scope():
    async with SessionFactory() as session:
        async with session.begin():
            yield session


async def get_or_register(session: AsyncSession, tg_user: TelegramUser, referral: str | None, settings: Settings):
    return await register_user(
        session, telegram_id=tg_user.id, username=tg_user.username,
        first_name=tg_user.first_name or "", last_name=tg_user.last_name or "",
        referral_code=referral, settings=settings,
    )
