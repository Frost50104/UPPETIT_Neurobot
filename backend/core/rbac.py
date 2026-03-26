from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from models.user import User, UserRole, Role, RolePermission, Permission
from database import get_db
from core.auth import get_current_active_user


class Perm:
    CHAT_USE = "chat:use"
    KB_MANAGE = "kb:manage"
    USER_MANAGE = "user:manage"
    ADMIN_PANEL = "admin:panel"


ALL_PERMISSIONS = {
    Perm.CHAT_USE: "Использование чата с ботом",
    Perm.KB_MANAGE: "Управление базой знаний",
    Perm.USER_MANAGE: "Управление пользователями",
    Perm.ADMIN_PANEL: "Доступ к панели администратора",
}

DEFAULT_ROLES = {
    "employee": [
        Perm.CHAT_USE,
    ],
    "admin": [
        Perm.CHAT_USE,
        Perm.KB_MANAGE,
        Perm.USER_MANAGE,
        Perm.ADMIN_PANEL,
    ],
}


async def load_user_with_roles(user_id: int, db: AsyncSession) -> User | None:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


def require_permission(permission_code: str):
    async def checker(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await load_user_with_roles(current_user.id, db)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        for user_role in user.roles:
            for rp in user_role.role.permissions:
                if rp.permission.code == permission_code:
                    return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {permission_code}",
        )
    return checker
