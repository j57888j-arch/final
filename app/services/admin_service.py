from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminRole, AdminUser, AdminUserRole, Permission, RolePermission, User

PERMISSIONS = {
    "orders.view": "Buyurtmalarni ko‘rish",
    "orders.manage": "Buyurtmalarni boshqarish",
    "catalog.manage": "Davlat va xizmatlarni boshqarish",
    "inventory.manage": "Zaxirani boshqarish",
    "payments.review": "To‘lovlarni tekshirish",
    "users.manage": "Foydalanuvchilarni boshqarish",
    "statistics.view": "Statistikani ko‘rish",
    "broadcast.create": "Ommaviy xabar yuborish",
    "support.manage": "Support murojaatlarini boshqarish",
    "roles.manage": "Admin rollarini boshqarish",
}

ROLE_PERMISSIONS = {
    "Super Admin": list(PERMISSIONS),
    "Manager": ["orders.view", "orders.manage", "catalog.manage", "inventory.manage", "statistics.view"],
    "Operator": ["orders.view", "orders.manage"],
    "Finance": ["payments.review", "statistics.view"],
    "Support": ["support.manage", "users.manage"],
    "Order Manager": ["orders.view", "orders.manage"],
    "Finance Admin": ["payments.review", "statistics.view"],
    "Support Admin": ["support.manage", "users.manage"],
    "Catalogue Manager": ["catalog.manage", "inventory.manage"],
}


async def ensure_bootstrap_admins(session: AsyncSession, admin_ids: set[int]) -> None:
    roles: dict[str, AdminRole] = {}
    for name in ROLE_PERMISSIONS:
        role = await session.scalar(select(AdminRole).where(AdminRole.name == name))
        if role is None:
            role = AdminRole(name=name, description=f"{name} role")
            session.add(role)
            await session.flush()
        roles[name] = role

    perms: dict[str, Permission] = {}
    for code, description in PERMISSIONS.items():
        perm = await session.scalar(select(Permission).where(Permission.code == code))
        if perm is None:
            perm = Permission(code=code, description=description)
            session.add(perm)
            await session.flush()
        perms[code] = perm

    for role_name, codes in ROLE_PERMISSIONS.items():
        for code in codes:
            exists = await session.get(RolePermission, (roles[role_name].id, perms[code].id))
            if not exists:
                session.add(RolePermission(role_id=roles[role_name].id, permission_id=perms[code].id))

    super_role = roles["Super Admin"]
    for tg_id in admin_ids:
        user = await session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            continue
        admin = await session.scalar(select(AdminUser).where(AdminUser.user_id == user.id))
        if admin is None:
            admin = AdminUser(user_id=user.id, is_active=True)
            session.add(admin)
            await session.flush()
        link = await session.get(AdminUserRole, (admin.id, super_role.id))
        if not link:
            session.add(AdminUserRole(admin_id=admin.id, role_id=super_role.id))


async def is_admin(session: AsyncSession, telegram_id: int, bootstrap_ids: set[int]) -> bool:
    if telegram_id in bootstrap_ids:
        return True
    user_id = await session.scalar(select(User.id).where(User.telegram_id == telegram_id))
    if not user_id:
        return False
    return bool(await session.scalar(select(AdminUser.id).where(AdminUser.user_id == user_id, AdminUser.is_active.is_(True))))


async def has_permission(session: AsyncSession, telegram_id: int, code: str, bootstrap_ids: set[int]) -> bool:
    if telegram_id in bootstrap_ids:
        return True
    query = (
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(AdminUserRole, AdminUserRole.role_id == RolePermission.role_id)
        .join(AdminUser, AdminUser.id == AdminUserRole.admin_id)
        .join(User, User.id == AdminUser.user_id)
        .where(User.telegram_id == telegram_id, AdminUser.is_active.is_(True), Permission.code == code)
    )
    return bool(await session.scalar(query))
