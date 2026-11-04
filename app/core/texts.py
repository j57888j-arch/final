from __future__ import annotations

from app.core.money import format_money


SEPARATOR = "━━━━━━━━━━━━━━━━━━"
WELCOME = (
    "🌐 WeraqamBot\n"
    "Virtual raqamlar va telekommunikatsiya xizmatlari markazi\n"
    f"{SEPARATOR}\n\n"
    "Assalomu alaykum! 👋\n"
    "Xizmatlarimizdan foydalanish uchun quyidagi bo‘limni tanlang."
)


def service_card(name: str, description: str, price: int, currency: str, available: int, scale: int) -> str:
    desc = (description or "Tavsif kiritilmagan.").strip()[:500]
    return (
        f"╭━━━ 🧩 {name} ━━━╮\n\n"
        f"{desc}\n\n"
        f"💳 Narx: {format_money(price, currency, scale)}\n"
        f"📦 Mavjud: {available} dona\n"
        f"{SEPARATOR}\n"
        "Xarid usulini tanlang:"
    )


def profile_card(user, balance: int, currency: str, scale: int, orders_total: int) -> str:
    username = f"@{user.username}" if user.username else "—"
    return (
        "╭━━━ 👤 PROFIL ━━━╮\n\n"
        f"🆔 ID: {user.telegram_id}\n"
        f"👤 Ism: {user.full_name or user.first_name}\n"
        f"🔗 Username: {username}\n"
        f"💳 Balans: {format_money(balance, currency, scale)}\n"
        f"📦 Buyurtmalar: {orders_total}\n"
        f"📅 Ro‘yxatdan o‘tgan: {user.created_at:%d.%m.%Y}\n"
        f"{SEPARATOR}\n"
        "Ma’lumotlaringiz himoyalangan."
    )
