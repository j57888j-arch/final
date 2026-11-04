from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.keyboards.main import USER_MENU

router = Router(name="fallback")


@router.message(StateFilter(None))
async def unknown_message(message: Message) -> None:
    await message.answer(
        "🤖 Buyruqni tushunmadim. Pastki menyudagi bo‘limlardan birini tanlang yoki /start yuboring.",
        reply_markup=USER_MENU,
    )
