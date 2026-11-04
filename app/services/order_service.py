from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.order_states import ensure_transition
from app.core.dates import as_utc
from app.database.models import (
    AdminUser, Inventory, InventoryItem, InventoryMovement, Order, OrderAssignment, OrderEvent, Payment,
    PromoCode, PromoRedemption, Referral, Service, User, OutboxEvent,
)
from app.services.common import audit, enqueue_message
from app.services.wallet_service import WalletError, post_wallet_transaction


class OrderError(Exception):
    pass


async def _discount_for(
    session: AsyncSession, *, user_id: int, promo_code: str | None, subtotal: int,
) -> tuple[PromoCode | None, int]:
    if not promo_code:
        return None, 0
    code = await session.scalar(
        select(PromoCode).where(PromoCode.code == promo_code.strip().upper(), PromoCode.is_active.is_(True)).with_for_update()
    )
    if not code:
        raise OrderError("Promo-kod topilmadi yoki faol emas.")
    now = datetime.now(timezone.utc)
    if code.starts_at and as_utc(code.starts_at) > now:
        raise OrderError("Bu promo-kod hali kuchga kirmagan.")
    if code.expires_at and as_utc(code.expires_at) <= now:
        raise OrderError("Promo-kodning amal qilish muddati tugagan.")
    if subtotal < code.min_order_minor:
        raise OrderError("Buyurtma summasi promo-kod uchun yetarli emas.")
    total_uses = int(await session.scalar(select(func.count(PromoRedemption.id)).where(
        PromoRedemption.promo_code_id == code.id,
        PromoRedemption.status.in_(["reserved", "applied"]),
    )) or 0)
    user_uses = int(await session.scalar(select(func.count(PromoRedemption.id)).where(
        PromoRedemption.promo_code_id == code.id, PromoRedemption.user_id == user_id,
        PromoRedemption.status.in_(["reserved", "applied"]),
    )) or 0)
    if code.max_uses is not None and total_uses >= code.max_uses:
        raise OrderError("Promo-kod foydalanish limitiga yetgan.")
    if user_uses >= code.per_user_limit:
        raise OrderError("Siz ushbu promo-koddan maksimal marta foydalangansiz.")
    if code.discount_type == "percent":
        if code.discount_value > 100:
            raise OrderError("Promo-kod foizi noto‘g‘ri sozlangan.")
        discount = subtotal * code.discount_value // 100
    elif code.discount_type == "fixed":
        discount = min(subtotal, code.discount_value)
    else:
        raise OrderError("Promo-kod chegirma turi noto‘g‘ri.")
    return code, discount


async def _reserve_inventory(session: AsyncSession, service_id: int, quantity: int) -> tuple[Inventory, list[InventoryItem]]:
    inventory = await session.scalar(select(Inventory).where(Inventory.service_id == service_id).with_for_update())
    if inventory is None:
        raise OrderError("Ushbu xizmat uchun zaxira hali sozlanmagan.")
    if inventory.available_quantity < quantity:
        raise OrderError("Afsuski, zaxira yetarli emas.")
    tracked_count = int(await session.scalar(
        select(func.count(InventoryItem.id)).where(InventoryItem.service_id == service_id)
    ) or 0)
    reserved_items: list[InventoryItem] = []
    if tracked_count:
        reserved_items = list((await session.scalars(
            select(InventoryItem).where(
                InventoryItem.service_id == service_id, InventoryItem.status == "available"
            ).order_by(InventoryItem.id).with_for_update(skip_locked=True).limit(quantity)
        )).all())
        if len(reserved_items) != quantity:
            raise OrderError("Individual raqam zaxirasi yetarli emas.")
        for item in reserved_items:
            item.status = "reserved"
    inventory.available_quantity -= quantity
    inventory.reserved_quantity += quantity
    await session.flush()
    session.add(InventoryMovement(
        inventory_id=inventory.id, movement_type="reserve", quantity=quantity,
        note="Buyurtma uchun rezerv qilindi",
    ))
    return inventory, reserved_items


async def create_wallet_order(
    session: AsyncSession, *, user: User, service_id: int, quantity: int,
    promo_code: str | None, settings: Settings,
) -> Order:
    if quantity < 1 or quantity > 50:
        raise OrderError("Miqdor 1 dan 50 gacha bo‘lishi kerak.")
    service = await session.scalar(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    if not service:
        raise OrderError("Xizmat topilmadi yoki faol emas.")
    if service.is_digital:
        raise OrderError("Raqamli xizmatlar Telegram ichida faqat Stars orqali sotilishi kerak. Stars xaridini tanlang.")
    wallet_currency = service.currency
    subtotal = service.price_minor * quantity
    promo, discount = await _discount_for(session, user_id=user.id, promo_code=promo_code, subtotal=subtotal)
    total = subtotal - discount
    inventory, reserved_items = await _reserve_inventory(session, service.id, quantity)
    order = Order(
        order_number=f"WR{datetime.now(timezone.utc):%y%m%d}{secrets.token_hex(3).upper()}",
        user_id=user.id, service_id=service.id, quantity=quantity,
        unit_price_minor=service.price_minor, total_minor=total, discount_minor=discount,
        currency=wallet_currency, status="paid", payment_method="wallet",
    )
    session.add(order)
    await session.flush()
    for item in reserved_items:
        item.order_id = order.id
    try:
        await post_wallet_transaction(
            session, user_id=user.id, amount_minor=total, currency=wallet_currency,
            transaction_type="debit", idempotency_key=f"order:{order.id}:debit",
            direction="debit", reference_type="order", reference_id=order.id,
            description=f"Buyurtma {order.order_number}",
        )
    except WalletError as exc:
        raise OrderError(str(exc)) from exc
    if promo:
        session.add(PromoRedemption(
            promo_code_id=promo.id, user_id=user.id, order_id=order.id, discount_minor=discount, status="applied",
        ))
    session.add(OrderEvent(order_id=order.id, old_status=None, new_status="paid", actor_telegram_id=user.telegram_id, comment="Wallet orqali to‘landi"))
    await audit(session, user.telegram_id, "order.created_and_paid", "order", order.id, {"service_id": service.id, "quantity": quantity})
    await enqueue_message(session, user.telegram_id, f"✅ Buyurtmangiz qabul qilindi. Raqam: {order.order_number}\nHolat: To‘lov qabul qilindi.")
    return order


async def create_stars_order(
    session: AsyncSession, *, user: User, service_id: int, quantity: int,
    promo_code: str | None, settings: Settings,
) -> tuple[Order, Payment]:
    if not settings.telegram_stars_enabled:
        raise OrderError("Telegram Stars to‘lovi hozircha o‘chirilgan.")
    if quantity < 1 or quantity > 50:
        raise OrderError("Miqdor 1 dan 50 gacha bo‘lishi kerak.")
    service = await session.scalar(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    if not service or not service.is_digital or not service.stars_price:
        raise OrderError("Bu raqamli xizmat uchun Stars narxi sozlanmagan.")
    subtotal = service.price_minor * quantity
    promo, discount = await _discount_for(session, user_id=user.id, promo_code=promo_code, subtotal=subtotal)
    total_local = subtotal - discount
    stars_amount = service.stars_price * quantity
    if promo and subtotal > 0:
        stars_amount = max(1, stars_amount * total_local // subtotal)
    inventory, reserved_items = await _reserve_inventory(session, service.id, quantity)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.payment_expiration_minutes)
    order = Order(
        order_number=f"WR{datetime.now(timezone.utc):%y%m%d}{secrets.token_hex(3).upper()}",
        user_id=user.id, service_id=service.id, quantity=quantity,
        unit_price_minor=service.price_minor, total_minor=total_local, discount_minor=discount,
        currency=service.currency, status="awaiting_payment", payment_method="stars", expires_at=expires_at,
    )
    session.add(order)
    await session.flush()
    for item in reserved_items:
        item.order_id = order.id
    payload = f"wrstars:{order.id}:{secrets.token_urlsafe(10)}"
    payment = Payment(
        user_id=user.id, order_id=order.id, provider="telegram_stars",
        amount_minor=stars_amount, currency="XTR", status="pending", payload=payload,
    )
    session.add(payment)
    if promo:
        session.add(PromoRedemption(
            promo_code_id=promo.id, user_id=user.id, order_id=order.id,
            discount_minor=discount, status="reserved",
        ))
    session.add(OrderEvent(order_id=order.id, old_status=None, new_status="awaiting_payment", actor_telegram_id=user.telegram_id, comment="Stars invoice tayyorlandi"))
    return order, payment


async def settle_stars_payment(
    session: AsyncSession, *, payload: str, telegram_charge_id: str, user_telegram_id: int,
    paid_amount: int, currency: str,
) -> tuple[Payment, Order]:
    payment = await session.scalar(select(Payment).where(Payment.payload == payload).with_for_update())
    if not payment or payment.provider != "telegram_stars":
        raise OrderError("To‘lov topilmadi.")
    if payment.user_id != (await session.scalar(select(User.id).where(User.telegram_id == user_telegram_id))):
        raise OrderError("To‘lov egasi mos kelmadi.")
    if payment.status == "paid":
        if payment.external_id != telegram_charge_id:
            raise OrderError("Takroriy to‘lov yangilanishidagi charge ID mos kelmadi.")
        order = await session.get(Order, payment.order_id)
        return payment, order
    if payment.status != "pending" or payment.amount_minor != paid_amount or currency != "XTR":
        raise OrderError("To‘lov qiymati yoki holati mos kelmadi.")
    order = await session.scalar(select(Order).where(Order.id == payment.order_id).with_for_update())
    if not order or order.status != "awaiting_payment":
        raise OrderError("Buyurtma to‘lov uchun yaroqli emas.")
    # The successful_payment update is authoritative after Telegram has accepted
    # pre-checkout. A delayed update must not be rejected merely because the local
    # checkout reservation's expiry timestamp passed while Telegram was processing it.
    ensure_transition(order.status, "paid")
    payment.status = "paid"
    payment.external_id = telegram_charge_id
    order.status = "paid"
    promo_redemption = await session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id).with_for_update())
    if promo_redemption and promo_redemption.status == "reserved":
        promo_redemption.status = "applied"
    session.add(OrderEvent(order_id=order.id, old_status="awaiting_payment", new_status="paid", actor_telegram_id=user_telegram_id, comment="Telegram Stars to‘lovi tasdiqlandi"))
    user = await session.get(User, order.user_id)
    if user:
        await enqueue_message(session, user.telegram_id, f"⭐ Stars to‘lovi qabul qilindi. Buyurtma: {order.order_number}")
    return payment, order


async def claim_order(session: AsyncSession, *, order_id: int, admin_telegram_id: int, bootstrap_ids: set[int]) -> Order:
    admin_user_id = await session.scalar(select(User.id).where(User.telegram_id == admin_telegram_id))
    if not admin_user_id:
        raise OrderError("Admin profili topilmadi.")
    admin = await session.scalar(select(AdminUser).where(AdminUser.user_id == admin_user_id, AdminUser.is_active.is_(True)))
    if not admin and admin_telegram_id not in bootstrap_ids:
        raise OrderError("Admin huquqi yo‘q.")
    if not admin:
        admin = AdminUser(user_id=admin_user_id, is_active=True)
        session.add(admin)
        await session.flush()
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != "paid":
        raise OrderError("Buyurtma mavjud emas yoki allaqachon qabul qilingan.")
    ensure_transition(order.status, "processing")
    order.status = "processing"
    order.claimed_by_admin_id = admin.id
    session.add(OrderAssignment(order_id=order.id, admin_id=admin.id))
    session.add(OrderEvent(order_id=order.id, old_status="paid", new_status="processing", actor_telegram_id=admin_telegram_id, comment="Admin buyurtmani qabul qildi"))
    user = await session.get(User, order.user_id)
    if user:
        await enqueue_message(session, user.telegram_id, f"🛠 Buyurtmangiz bajarilmoqda. Raqam: {order.order_number}")
    await audit(session, admin_telegram_id, "order.claimed", "order", order.id)
    return order


async def complete_order(session: AsyncSession, *, order_id: int, admin_telegram_id: int, settings: Settings | None = None) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != "processing":
        raise OrderError("Faqat bajarilayotgan buyurtma yakunlanishi mumkin.")
    admin = await session.get(AdminUser, order.claimed_by_admin_id) if order.claimed_by_admin_id else None
    actor_user_id = await session.scalar(select(User.id).where(User.telegram_id == admin_telegram_id))
    if not admin or admin.user_id != actor_user_id:
        raise OrderError("Bu buyurtma boshqa admin tomonidan qabul qilingan.")
    inventory = await session.scalar(select(Inventory).where(Inventory.service_id == order.service_id).with_for_update())
    if not inventory or inventory.reserved_quantity < order.quantity:
        raise OrderError("Zaxira holati nomuvofiq. Super admin tekshiruvi kerak.")
    inventory.reserved_quantity -= order.quantity
    inventory.sold_quantity += order.quantity
    inventory.total_quantity = inventory.available_quantity + inventory.reserved_quantity + inventory.sold_quantity
    inventory.updated_at = datetime.now(timezone.utc)
    tracked_items = list((await session.scalars(
        select(InventoryItem).where(InventoryItem.order_id == order.id, InventoryItem.status == "reserved").with_for_update()
    )).all())
    delivered_resources: list[str] = []
    if tracked_items:
        from app.config import get_settings
        from app.core.crypto import decrypt_resource
        active_settings = settings or get_settings()
        encryption_key = active_settings.phone_encryption_key.get_secret_value()
        if len(tracked_items) != order.quantity or not encryption_key:
            raise OrderError("Individual zaxira yoki encryption key mos emas; buyurtma yakunlanmadi.")
        try:
            for item in tracked_items:
                delivered_resources.append(decrypt_resource(item.resource_ciphertext, encryption_key))
                item.status = "sold"
        except ValueError as exc:
            raise OrderError(str(exc)) from exc
    session.add(InventoryMovement(inventory_id=inventory.id, movement_type="sold", quantity=order.quantity, reference_id=order.id, admin_telegram_id=admin_telegram_id, note="Buyurtma bajarildi"))
    old = order.status
    ensure_transition(old, "completed")
    order.status = "completed"
    order.completed_at = datetime.now(timezone.utc)
    session.add(OrderEvent(order_id=order.id, old_status=old, new_status="completed", actor_telegram_id=admin_telegram_id, comment="Admin buyurtmani yakunladi"))
    user = await session.get(User, order.user_id)
    if user:
        resource_block = ""
        if delivered_resources:
            resource_block = "\n\n📱 Sizga ajratilgan telekommunikatsiya resursi:\n" + "\n".join(delivered_resources)
            resource_block += "\n\n⚠️ Bot SMS/OTP tasdiqlash kodlari yoki akkaunt parollarini qabul qilmaydi."
        completion_text = f"🎉 Buyurtmangiz bajarildi!\nBuyurtma: {order.order_number}{resource_block}"
        if delivered_resources:
            # Keep the delivered number encrypted while it waits in the transactional outbox.
            from app.core.crypto import encrypt_sensitive_text
            ciphertext = encrypt_sensitive_text(completion_text, encryption_key)
            session.add(OutboxEvent(
                event_type="send_encrypted_message",
                payload={"chat_id": user.telegram_id, "ciphertext": ciphertext},
            ))
        else:
            await enqueue_message(session, user.telegram_id, completion_text)
    await _reward_referral(session, user, order)
    await audit(session, admin_telegram_id, "order.completed", "order", order.id)
    return order


async def _reward_referral(session: AsyncSession, user: User | None, order: Order) -> None:
    from app.services.wallet_service import post_wallet_transaction
    from app.config import get_settings

    if not user:
        return
    referral = await session.scalar(select(Referral).where(Referral.referred_user_id == user.id, Referral.status == "pending").with_for_update())
    if not referral:
        return
    bonus = int(referral.bonus_minor or get_settings().referral_bonus_minor)
    if bonus > 0:
        await post_wallet_transaction(
            session, user_id=referral.referrer_user_id, amount_minor=bonus,
            currency=order.currency, transaction_type="referral_bonus",
            idempotency_key=f"referral:{referral.id}:bonus", direction="credit",
            reference_type="referral", reference_id=referral.id,
            description=f"Referal bonusi: {order.order_number}",
        )
        referrer = await session.get(User, referral.referrer_user_id)
        if referrer:
            await enqueue_message(session, referrer.telegram_id, f"🎁 Referal bonusi: {bonus} {order.currency} hisobingizga qo‘shildi.")
    referral.status = "rewarded"
    referral.rewarded_at = datetime.now(timezone.utc)


async def reject_order(
    session: AsyncSession, *, order_id: int, admin_telegram_id: int,
    settings: Settings, stars_refund_confirmed: bool = False,
) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status not in {"paid", "processing", "awaiting_payment", "refund_pending"}:
        raise OrderError("Bu buyurtmani rad etib bo‘lmaydi.")
    if order.payment_method == "stars" and order.status in {"paid", "processing", "refund_pending"} and not stars_refund_confirmed:
        raise OrderError("Stars to‘lovi avval Telegram orqali qaytarilishi kerak.")
    if order.status == "processing":
        admin = await session.get(AdminUser, order.claimed_by_admin_id) if order.claimed_by_admin_id else None
        actor_user_id = await session.scalar(select(User.id).where(User.telegram_id == admin_telegram_id))
        if not admin or admin.user_id != actor_user_id:
            raise OrderError("Bu buyurtma boshqa admin tomonidan qabul qilingan.")
    inventory = await session.scalar(select(Inventory).where(Inventory.service_id == order.service_id).with_for_update())
    old_status = order.status
    if not inventory or inventory.reserved_quantity < order.quantity:
        raise OrderError("Zaxira rezervi topilmadi. Buyurtma holati o‘zgartirilmadi.")
    inventory.reserved_quantity -= order.quantity
    inventory.available_quantity += order.quantity
    inventory.total_quantity = inventory.available_quantity + inventory.reserved_quantity + inventory.sold_quantity
    reserved_items = (await session.scalars(
        select(InventoryItem).where(InventoryItem.order_id == order.id, InventoryItem.status == "reserved").with_for_update()
    )).all()
    for item in reserved_items:
        item.status = "available"
        item.order_id = None
    session.add(InventoryMovement(inventory_id=inventory.id, movement_type="release", quantity=order.quantity, reference_id=order.id, admin_telegram_id=admin_telegram_id, note="Buyurtma rad etildi"))
    if order.payment_method == "wallet" and order.status in {"paid", "processing"}:
        await post_wallet_transaction(
            session, user_id=order.user_id, amount_minor=order.total_minor,
            currency=order.currency, transaction_type="refund",
            idempotency_key=f"order:{order.id}:refund", direction="refund",
            reference_type="order", reference_id=order.id,
            description=f"Buyurtma qaytarildi: {order.order_number}",
        )
    new_status = "refunded" if order.payment_method == "wallet" or stars_refund_confirmed else "cancelled"
    ensure_transition(old_status, new_status)
    order.status = new_status
    if old_status == "awaiting_payment":
        promo_redemption = await session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id).with_for_update())
        if promo_redemption and promo_redemption.status == "reserved":
            promo_redemption.status = "expired"
    session.add(OrderEvent(order_id=order.id, old_status=old_status, new_status=order.status, actor_telegram_id=admin_telegram_id, comment="Admin buyurtmani rad etdi"))
    user = await session.get(User, order.user_id)
    if user:
        await enqueue_message(session, user.telegram_id, f"⚠️ Buyurtma bekor qilindi: {order.order_number}." + (" Mablag‘ balansingizga qaytarildi." if order.payment_method == "wallet" or stars_refund_confirmed else ""))
    await audit(session, admin_telegram_id, "order.rejected", "order", order.id)
    return order


async def expire_unpaid_orders(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    rows = (await session.scalars(select(Order).where(
        Order.status == "awaiting_payment", Order.expires_at.is_not(None), Order.expires_at < now
    ).with_for_update(skip_locked=True).limit(100))).all()
    count = 0
    for order in rows:
        inventory = await session.scalar(select(Inventory).where(Inventory.service_id == order.service_id).with_for_update())
        if not inventory or inventory.reserved_quantity < order.quantity:
            await audit(
                session, None, "order.expiry_inventory_mismatch", "order", order.id,
                {"service_id": order.service_id, "quantity": order.quantity},
            )
            continue
        inventory.reserved_quantity -= order.quantity
        inventory.available_quantity += order.quantity
        inventory.total_quantity = inventory.available_quantity + inventory.reserved_quantity + inventory.sold_quantity
        reserved_items = (await session.scalars(
            select(InventoryItem).where(InventoryItem.order_id == order.id, InventoryItem.status == "reserved").with_for_update()
        )).all()
        for item in reserved_items:
            item.status = "available"
            item.order_id = None
        session.add(InventoryMovement(
            inventory_id=inventory.id, movement_type="release", quantity=order.quantity,
            reference_id=order.id, note="To‘lov muddati tugagani uchun zaxira bo‘shatildi",
        ))
        ensure_transition(order.status, "cancelled")
        order.status = "cancelled"
        promo_redemption = await session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id).with_for_update())
        if promo_redemption and promo_redemption.status == "reserved":
            promo_redemption.status = "expired"
        session.add(OrderEvent(order_id=order.id, old_status="awaiting_payment", new_status="cancelled", comment="To‘lov muddati tugadi"))
        payment = await session.scalar(select(Payment).where(Payment.order_id == order.id, Payment.status == "pending"))
        if payment:
            payment.status = "expired"
        user = await session.get(User, order.user_id)
        if user:
            await enqueue_message(
                session, user.telegram_id,
                f"⌛ {order.order_number} buyurtmasi uchun to‘lov muddati tugadi. Zaxira bo‘shatildi.",
            )
        count += 1
    return count
