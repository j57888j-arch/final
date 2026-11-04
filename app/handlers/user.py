from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, LabeledPrice, Message, PreCheckoutQuery,
)
from sqlalchemy import desc, func, select

from app.config import Settings
from app.core.money import format_money, parse_amount
from app.core.dates import as_utc
from app.core.texts import SEPARATOR, WELCOME, profile_card, service_card
from app.database.models import (
    Order, Payment, PromoCode, Service, User, WalletAccount, OutboxEvent,
)
from app.database.session import SessionFactory
from app.handlers.utils import get_or_register, session_scope
from app.keyboards.main import (
    ADMIN_MENU, USER_MENU, countries_keyboard, service_actions, services_keyboard,
)
from app.services.catalog_service import active_countries, get_service, services_for_country
from app.services.common import enqueue_message
from app.services.order_service import (
    OrderError, create_stars_order, create_wallet_order, settle_stars_payment,
)
from app.services.admin_service import is_admin
from app.services.payment_service import (
    PaymentError, attach_payment_proof, create_manual_topup,
)
from app.services.support_service import create_ticket
from app.services.user_service import count_user_orders, get_wallet_balance
from app.states.forms import PromoStates, SupportStates, TopUpStates

router = Router(name="user")


def _settings(settings: Settings | None) -> Settings:
    if settings is None:
        from app.config import get_settings
        return get_settings()
    return settings


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    payload = ""
    if message.text and len(message.text.split(maxsplit=1)) == 2:
        payload = message.text.split(maxsplit=1)[1].strip()
    referral = payload.removeprefix("ref_") if payload.startswith("ref_") else None
    async with session_scope() as session:
        user, _ = await get_or_register(session, message.from_user, referral, settings)
        if user.is_blocked:
            await message.answer("⛔ Hisobingiz vaqtincha cheklangan. Support bilan bog‘laning.")
            return
        admin = await is_admin(session, message.from_user.id, settings.admin_ids)
    await message.answer(WELCOME, reply_markup=ADMIN_MENU if admin else USER_MENU)


@router.message(F.text.in_({"🌍 Raqamlar katalogi", "🌍 Xizmatlar"}))
async def catalog_message(message: Message, settings: Settings) -> None:
    async with session_scope() as session:
        countries = await active_countries(session)
    if not countries:
        await message.answer("🌍 Hozircha katalogda faol davlatlar yo‘q. Tez orada yangilanadi.", reply_markup=USER_MENU)
        return
    await message.answer("╭━━ 🌍 DAVLATLAR ━━╮\n\nXizmat ko‘rsatiladigan davlatni tanlang:", reply_markup=countries_keyboard(countries))




@router.callback_query(F.data == "home")
async def home_callback(call: CallbackQuery) -> None:
    await call.message.answer(WELCOME, reply_markup=USER_MENU)
    await call.answer()


@router.callback_query(F.data == "catalog")
async def catalog_callback(call: CallbackQuery, settings: Settings) -> None:
    async with session_scope() as session:
        countries = await active_countries(session)
    await call.message.edit_text(
        "╭━━ 🌍 DAVLATLAR ━━╮\n\nXizmat ko‘rsatiladigan davlatni tanlang:",
        reply_markup=countries_keyboard(countries),
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^country:\d+$"))
async def country_callback(call: CallbackQuery) -> None:
    country_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        services = await services_for_country(session, country_id)
    if not services:
        await call.answer("Bu davlatda hozircha xizmat yo‘q.", show_alert=True)
        return
    await call.message.edit_text("╭━━ 🧩 XIZMATLAR ━━╮\n\nKerakli xizmatni tanlang:", reply_markup=services_keyboard(services))
    await call.answer()


@router.callback_query(F.data.regexp(r"^service:\d+$"))
async def service_callback(call: CallbackQuery, settings: Settings) -> None:
    service_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        item = await get_service(session, service_id)
    if not item:
        await call.answer("Xizmat topilmadi.", show_alert=True)
        return
    service, available = item
    stars = bool(settings.telegram_stars_enabled and service.stars_price and service.is_digital)
    wallet = not service.is_digital
    text = service_card(service.name, service.description, service.price_minor, service.currency, available, settings.money_scale)
    if service.is_digital and not stars:
        text += "\n\nℹ️ Bu raqamli xizmat uchun Telegram Stars narxi sozlanmagan yoki Stars to‘lovi o‘chiq."
    if not service.is_digital and not wallet:
        text += "\n\nℹ️ To‘lov usuli sozlanmagan."
    await call.message.edit_text(text, reply_markup=service_actions(service.id, stars_available=stars, wallet_available=wallet))
    await call.answer()


@router.callback_query(F.data.startswith("buywallet:"))
async def buy_wallet_callback(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    service_id = int(call.data.split(":", 1)[1])
    promo = (await state.get_data()).get("promo_code")
    try:
        async with session_scope() as session:
            user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
            if not user:
                raise OrderError("Avval /start orqali ro‘yxatdan o‘ting.")
            order = await create_wallet_order(session, user=user, service_id=service_id, quantity=1, promo_code=promo, settings=settings)
            for admin_id in settings.admin_ids:
                await enqueue_message(
                    session, admin_id,
                    f"🆕 Yangi buyurtma #{order.order_number}\nXizmat ID: {service_id}\nBuyurtma ID: {order.id}\nFoydalanuvchi: {call.from_user.id}",
                )
        await state.update_data(promo_code=None)
        await call.message.edit_text(f"✅ Xarid muvaffaqiyatli!\n\n📦 Buyurtma: {order.order_number}\n🕒 Holat: Operator navbatida.")
        await call.answer("Buyurtma qabul qilindi")
    except (OrderError, ValueError) as exc:
        await call.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("buystars:"))
async def buy_stars_callback(call: CallbackQuery, state: FSMContext, bot, settings: Settings) -> None:
    service_id = int(call.data.split(":", 1)[1])
    promo = (await state.get_data()).get("promo_code")
    try:
        async with session_scope() as session:
            user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
            if not user:
                raise OrderError("Avval /start orqali ro‘yxatdan o‘ting.")
            order, payment = await create_stars_order(session, user=user, service_id=service_id, quantity=1, promo_code=promo, settings=settings)
        await state.update_data(promo_code=None)
        async with session_scope() as session:
            service = await session.get(Service, service_id)
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=(service.name if service else "WeraqamBot xizmati")[:32],
            description=(service.description or "Xizmat uchun to‘lov")[:255],
            payload=payment.payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=(service.name if service else "Xizmat")[:32], amount=payment.amount_minor)],
        )
        await call.answer("Stars invoice yuborildi")
    except (OrderError, ValueError) as exc:
        await call.answer(str(exc), show_alert=True)


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery) -> None:
    from app.database.models import Payment
    now = datetime.now(timezone.utc)
    ok = False
    async with session_scope() as session:
        payment = await session.scalar(
            select(Payment).where(Payment.payload == query.invoice_payload).with_for_update()
        )
        checkout_user = await session.scalar(select(User).where(User.telegram_id == query.from_user.id))
        if (
            payment and payment.provider == "telegram_stars" and payment.status == "pending"
            and payment.amount_minor == query.total_amount and payment.currency == query.currency == "XTR"
            and checkout_user and not checkout_user.is_blocked
            and payment.user_id == checkout_user.id and payment.order_id is not None
        ):
            order = await session.scalar(
                select(Order).where(Order.id == payment.order_id).with_for_update()
            )
            if (
                order and order.status == "awaiting_payment"
                and (order.expires_at is None or (as_utc(order.expires_at) and as_utc(order.expires_at) > now))
            ):
                # The checkout is already in progress; give Telegram's payment confirmation
                # a short grace period so the expiry worker cannot release its inventory.
                order.expires_at = now + timedelta(minutes=10)
                ok = True
    await query.answer(
        ok=ok,
        error_message=None if ok else "To‘lov tafsilotlari noto‘g‘ri yoki buyurtma muddati tugagan.",
    )


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, settings: Settings) -> None:
    successful = message.successful_payment
    if not successful:
        return
    try:
        async with session_scope() as session:
            # Lock and inspect the payment first. Only the first successful update
            # should enqueue admin alerts; Telegram may redeliver the same update.
            payment_before = await session.scalar(
                select(Payment).where(Payment.payload == successful.invoice_payload).with_for_update()
            )
            first_confirmation = bool(payment_before and payment_before.status == "pending")
            payment, order = await settle_stars_payment(
                session, payload=successful.invoice_payload,
                telegram_charge_id=successful.telegram_payment_charge_id,
                user_telegram_id=message.from_user.id,
                paid_amount=successful.total_amount, currency=successful.currency,
            )
            if first_confirmation:
                for admin_id in settings.admin_ids:
                    await enqueue_message(
                        session, admin_id,
                        f"⭐ Stars buyurtma #{order.order_number}\nOrder ID: {order.id}\nUser: {message.from_user.id}",
                    )
        # The order service writes the user's confirmation to the transactional
        # outbox. Do not send directly here, so retries cannot duplicate messages.
    except OrderError as exc:
        await message.answer(f"⚠️ To‘lov qayd etildi, lekin buyurtma avtomatik tasdiqlanmadi. Supportga murojaat qiling.\nKod: {str(exc)[:180]}")


@router.message(F.text == "📦 Buyurtmalarim")
async def my_orders_handler(message: Message) -> None:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        rows = (await session.scalars(select(Order).where(Order.user_id == user.id).order_by(desc(Order.created_at)).limit(10))).all() if user else []
        services = {row.id: await session.get(Service, row.service_id) for row in rows}
    if not rows:
        await message.answer("📦 Sizda hali buyurtmalar yo‘q.", reply_markup=USER_MENU)
        return
    lines = ["╭━━ 📦 BUYURTMALARIM ━━╮"]
    status_names = {"awaiting_payment": "To‘lov kutilmoqda", "paid": "Operator navbatida", "processing": "Bajarilmoqda", "completed": "Bajarildi", "cancelled": "Bekor qilindi", "rejected": "Rad etildi", "refunded": "Qaytarildi", "refund_pending": "To‘lov qaytarilmoqda"}
    for order in rows:
        service = services.get(order.id)
        lines.append(f"\n🔹 {order.order_number}\n🧩 {service.name if service else 'Xizmat'}\n📌 {status_names.get(order.status, order.status)}")
    await message.answer("\n".join(lines), reply_markup=USER_MENU)


@router.message(F.text == "💳 Hisobim")
async def wallet_handler(message: Message, settings: Settings) -> None:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        balance = await get_wallet_balance(session, user.id) if user else 0
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    if settings.payment_mode == "manual":
        rows.append([InlineKeyboardButton(text="➕ Balans to‘ldirish", callback_data="topup:start")])
    await message.answer(
        f"╭━━━ 💳 HISOBIM ━━━╮\n\n"
        f"💰 Joriy balans: {format_money(balance, settings.default_currency, settings.money_scale)}\n"
        f"{SEPARATOR}\n"
        "Barcha kirim-chiqimlar xavfsiz tranzaksiya jurnalida saqlanadi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else USER_MENU,
    )


@router.callback_query(F.data == "topup:start")
async def topup_start(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if settings.payment_mode != "manual":
        await call.answer("To‘lov usuli o‘chiq.", show_alert=True)
        return
    await state.set_state(TopUpStates.amount)
    await call.message.answer("💳 To‘ldirmoqchi bo‘lgan summani kiriting (masalan: 50000):", reply_markup=USER_MENU)
    await call.answer()


@router.message(TopUpStates.amount)
async def topup_amount(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        amount = parse_amount(message.text or "", settings.money_scale)
        async with session_scope() as session:
            user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            payment = await create_manual_topup(session, user=user, amount_minor=amount, settings=settings)
        await state.update_data(payment_id=payment.id)
        await state.set_state(TopUpStates.proof)
        await message.answer(
            f"╭━━ 💳 TO‘LOV ━━╮\n\n"
            f"🧾 To‘lov ID: #{payment.id}\n"
            f"💰 Summa: {format_money(amount, settings.default_currency, settings.money_scale)}\n"
            f"🏦 Karta: {settings.payment_card_number}\n"
            f"👤 Qabul qiluvchi: {settings.payment_card_holder or '—'}\n\n"
            "To‘lovdan so‘ng chek rasmini shu yerga yuboring. Admin tekshirganidan keyin balansingiz to‘ldiriladi."
        )
    except (ValueError, PaymentError) as exc:
        await message.answer(f"⚠️ {exc}")


@router.message(TopUpStates.proof, F.photo)
async def topup_proof(message: Message, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    payment_id = data.get("payment_id")
    file_id = message.photo[-1].file_id
    try:
        async with session_scope() as session:
            user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            payment = await attach_payment_proof(session, payment_id=payment_id, user_id=user.id, file_id=file_id)
        caption = f"🧾 Yangi to‘lov cheki\nID: #{payment.id}\nUser: {message.from_user.id}\nSumma: {format_money(payment.amount_minor, payment.currency, settings.money_scale)}"
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=__import__("app.keyboards.main", fromlist=["payment_review"]).payment_review(payment.id))
            except Exception:
                pass
        await state.clear()
        await message.answer("✅ Chek qabul qilindi. Admin tekshiruvini kuting.", reply_markup=USER_MENU)
    except PaymentError as exc:
        await message.answer(f"⚠️ {exc}")


@router.message(F.text == "👤 Profilim")
async def profile_handler(message: Message, settings: Settings) -> None:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user:
            await message.answer("Avval /start bosing.")
            return
        balance = await get_wallet_balance(session, user.id)
        order_count = await count_user_orders(session, user.id)
        text = profile_card(user, balance, settings.default_currency, settings.money_scale, order_count)
    await message.answer(text, reply_markup=USER_MENU)


@router.message(F.text.in_({"👥 Referal", "🎟 Referal"}))
async def referral_handler(message: Message, bot) -> None:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        count = int(await session.scalar(select(func.count(User.id)).where(User.referred_by_id == user.id)) or 0) if user else 0
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user.referral_code}" if user else ""
    await message.answer(
        f"╭━━ 🎟 REFERAL ━━╮\n\n"
        f"👥 Taklif qilganlaringiz: {count}\n"
        f"🔗 Sizning havolangiz:\n{link}\n\n"
        "Bonus faqat taklif qilingan foydalanuvchi birinchi buyurtmasini muvaffaqiyatli bajarganidan so‘ng beriladi.",
        reply_markup=USER_MENU,
    )


@router.message(F.text.in_({"🎟 Promo-kod", "🏷 Promo-kod"}))
async def promo_start(message: Message, state: FSMContext) -> None:
    await state.set_state(PromoStates.code)
    await message.answer("🏷 Promo-kodni kiriting:", reply_markup=USER_MENU)


@router.message(PromoStates.code)
async def promo_receive(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().upper()
    async with session_scope() as session:
        promo = await session.scalar(select(PromoCode).where(PromoCode.code == code, PromoCode.is_active.is_(True)))
    if not promo:
        await message.answer("❌ Promo-kod topilmadi yoki faol emas. Qayta kiriting:")
        return
    if promo.expires_at and as_utc(promo.expires_at) <= datetime.now(timezone.utc):
        await message.answer("❌ Promo-kod muddati tugagan.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(None)
    discount = f"{promo.discount_value}%" if promo.discount_type == "percent" else format_money(promo.discount_value, "UZS", 100)
    await message.answer(f"✅ Promo-kod saqlandi: {code}\nChegirma: {discount}\nEndi katalogdan xizmat tanlang.", reply_markup=USER_MENU)


@router.message(F.text == "💬 Yordam")
async def support_start(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.set_state(SupportStates.message)
    hint = f"\nSupport: @{settings.support_username}" if settings.support_username else ""
    await message.answer("💬 Murojaatingizni bitta xabarda yozing. Operatorlar javob beradi." + hint, reply_markup=USER_MENU)


@router.message(SupportStates.message)
async def support_receive(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        async with session_scope() as session:
            user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            ticket = await create_ticket(session, user=user, message=message.text or "", admin_ids=settings.admin_ids)
        await state.clear()
        await message.answer(f"✅ Murojaatingiz qabul qilindi. Ticket: #{ticket.id}", reply_markup=USER_MENU)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")


@router.message(F.text == "❌ Bekor qilish")
async def cancel_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Amal bekor qilindi.", reply_markup=USER_MENU)
