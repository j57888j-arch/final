from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Country, Inventory, InventoryItem, InventoryMovement, Service
from app.services.common import audit


async def active_countries(session: AsyncSession) -> list[Country]:
    return list((await session.scalars(select(Country).where(Country.is_active.is_(True)).order_by(Country.name))).all())


async def services_for_country(session: AsyncSession, country_id: int) -> list[tuple[Service, int]]:
    rows = (await session.execute(
        select(Service, Inventory.available_quantity)
        .join(Inventory, Inventory.service_id == Service.id)
        .where(Service.country_id == country_id, Service.is_active.is_(True))
        .order_by(Service.name)
    )).all()
    return [(service, available or 0) for service, available in rows]


async def get_service(session: AsyncSession, service_id: int) -> tuple[Service, int] | None:
    result = await session.execute(
        select(Service, Inventory.available_quantity)
        .join(Inventory, Inventory.service_id == Service.id)
        .where(Service.id == service_id)
    )
    row = result.first()
    return (row[0], row[1] or 0) if row else None


async def create_country(
    session: AsyncSession, *, name: str, emoji: str, description: str, admin_telegram_id: int | None = None,
) -> Country:
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Davlat nomi 1–120 belgidan iborat bo‘lishi kerak.")
    country = Country(name=name, emoji=(emoji or "🌍")[:16], description=description.strip()[:500])
    session.add(country)
    await session.flush()
    await audit(session, admin_telegram_id, "country.created", "country", country.id, {"name": country.name})
    return country


async def create_service(
    session: AsyncSession, *, country_id: int, name: str, description: str,
    price_minor: int, currency: str, initial_stock: int,
    stars_price: int | None, is_digital: bool, admin_telegram_id: int | None = None,
) -> Service:
    country = await session.get(Country, country_id)
    if not country or not country.is_active:
        raise ValueError("Davlat topilmadi yoki faol emas.")
    if price_minor <= 0 or initial_stock < 0:
        raise ValueError("Narx 0 dan katta, zaxira esa manfiy bo‘lmasligi kerak.")
    if is_digital and not stars_price:
        # Keep listing possible, but the service cannot be purchased until Stars price is set.
        stars_price = None
    service = Service(
        country_id=country_id, name=name.strip()[:160], description=description.strip()[:1000],
        price_minor=price_minor, currency=currency.upper(), stars_price=stars_price,
        is_digital=is_digital, is_active=True,
    )
    session.add(service)
    await session.flush()
    inventory = Inventory(
        service_id=service.id, total_quantity=initial_stock,
        available_quantity=initial_stock, reserved_quantity=0, sold_quantity=0,
    )
    session.add(inventory)
    await session.flush()
    if initial_stock:
        session.add(InventoryMovement(
            inventory_id=inventory.id, movement_type="initial", quantity=initial_stock,
            admin_telegram_id=admin_telegram_id, note="Xizmat yaratildi",
        ))
    await audit(
        session, admin_telegram_id, "service.created", "service", service.id,
        {"name": service.name, "country_id": country_id, "is_digital": is_digital},
    )
    return service


async def set_available_stock(
    session: AsyncSession, *, service_id: int, available_quantity: int, admin_telegram_id: int,
) -> Inventory:
    if available_quantity < 0:
        raise ValueError("Zaxira manfiy bo‘lishi mumkin emas.")
    inventory = await session.scalar(select(Inventory).where(Inventory.service_id == service_id).with_for_update())
    if not inventory:
        raise ValueError("Zaxira topilmadi.")
    tracked_item_id = await session.scalar(select(InventoryItem.id).where(
        InventoryItem.service_id == service_id
    ).limit(1))
    if tracked_item_id is not None:
        raise ValueError("Individual raqamlar rejimida umumiy zaxirani tahrirlab bo‘lmaydi; /inventory_add yoki /inventory_retire ishlating.")
    old_available = inventory.available_quantity
    inventory.available_quantity = available_quantity
    inventory.total_quantity = available_quantity + inventory.reserved_quantity + inventory.sold_quantity
    session.add(InventoryMovement(
        inventory_id=inventory.id, movement_type="admin_adjustment",
        quantity=available_quantity - old_available, admin_telegram_id=admin_telegram_id,
        note="Admin zaxirani yangiladi",
    ))
    await audit(
        session, admin_telegram_id, "inventory.adjusted", "inventory", inventory.id,
        {"old_available": old_available, "new_available": available_quantity},
    )
    return inventory


async def set_country_active(
    session: AsyncSession, *, country_id: int, is_active: bool, admin_telegram_id: int,
) -> Country:
    country = await session.scalar(select(Country).where(Country.id == country_id).with_for_update())
    if not country:
        raise ValueError("Davlat topilmadi.")
    country.is_active = is_active
    await audit(
        session, admin_telegram_id, "country.status_changed", "country", country.id,
        {"is_active": is_active},
    )
    return country


async def set_service_active(
    session: AsyncSession, *, service_id: int, is_active: bool, admin_telegram_id: int,
) -> Service:
    service = await session.scalar(select(Service).where(Service.id == service_id).with_for_update())
    if not service:
        raise ValueError("Xizmat topilmadi.")
    service.is_active = is_active
    await audit(
        session, admin_telegram_id, "service.status_changed", "service", service.id,
        {"is_active": is_active},
    )
    return service


async def update_service_price(
    session: AsyncSession, *, service_id: int, price_minor: int, admin_telegram_id: int,
) -> Service:
    if price_minor <= 0:
        raise ValueError("Narx 0 dan katta bo‘lishi kerak.")
    service = await session.scalar(select(Service).where(Service.id == service_id).with_for_update())
    if not service:
        raise ValueError("Xizmat topilmadi.")
    old_price = service.price_minor
    service.price_minor = price_minor
    await audit(
        session, admin_telegram_id, "service.price_changed", "service", service.id,
        {"old_price_minor": old_price, "new_price_minor": price_minor},
    )
    return service
