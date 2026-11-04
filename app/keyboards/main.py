from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

USER_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌍 Raqamlar katalogi"), KeyboardButton(text="📦 Buyurtmalarim")],
        [KeyboardButton(text="💳 Hisobim"), KeyboardButton(text="👤 Profilim")],
        [KeyboardButton(text="🎟 Promo-kod"), KeyboardButton(text="👥 Referal")],
        [KeyboardButton(text="💬 Yordam")],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="Kerakli bo‘limni tanlang…",
)

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Dashboard"), KeyboardButton(text="📦 Buyurtmalar")],
        [KeyboardButton(text="👥 Foydalanuvchilar"), KeyboardButton(text="💳 To‘lovlar")],
        [KeyboardButton(text="🌍 Davlatlar"), KeyboardButton(text="🧩 Xizmatlar")],
        [KeyboardButton(text="📦 Zaxira"), KeyboardButton(text="🎟 Promo yaratish")],
        [KeyboardButton(text="📈 Hisobotlar"), KeyboardButton(text="📢 Xabar yuborish")],
        [KeyboardButton(text="🛡 Admin rollari")],
        [KeyboardButton(text="🔙 Bosh menyu")],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="Admin boshqaruvi…",
)


def countries_keyboard(countries) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{c.emoji} {c.name}", callback_data=f"country:{c.id}")] for c in countries]
    rows.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_keyboard(services) -> InlineKeyboardMarkup:
    rows = []
    for service, available in services:
        rows.append([InlineKeyboardButton(
            text=f"🧩 {service.name} · {available} dona",
            callback_data=f"service:{service.id}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Davlatlar", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_actions(service_id: int, *, stars_available: bool, wallet_available: bool) -> InlineKeyboardMarkup:
    rows = []
    if wallet_available:
        rows.append([InlineKeyboardButton(text="💳 Balansdan xarid qilish", callback_data=f"buywallet:{service_id}")])
    if stars_available:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars orqali", callback_data=f"buystars:{service_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Xizmatlarga qaytish", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_actions(order_id: int, *, can_manage: bool = False) -> InlineKeyboardMarkup:
    if not can_manage:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"orderclaim:{order_id}")],
        [InlineKeyboardButton(text="🎉 Bajarildi", callback_data=f"orderdone:{order_id}"),
         InlineKeyboardButton(text="✖️ Rad etish", callback_data=f"orderreject:{order_id}")],
    ])


def payment_review(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"payok:{payment_id}"),
        InlineKeyboardButton(text="✖️ Rad etish", callback_data=f"payno:{payment_id}"),
    ]])


def stars_pay_button(payment_id: int, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐ Stars invoice tayyorlash", callback_data=f"starsinvoice:{payment_id}:{order_id}")
    ]])


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True)


def choose_country_keyboard(countries) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{c.emoji} {c.name}", callback_data=f"admincountry:{c.id}")]
        for c in countries
    ])


def admin_service_keyboard(services) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{s.name} · #{s.id}", callback_data=f"adminstock:{s.id}")]
        for s in services
    ])
