import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from database import get_db
from models.user import User, UserRole, Role, RolePermission, Permission
from schemas.user import UserOut, UserCreate, UserUpdate
from core.rbac import require_permission, Perm, load_user_with_roles
from core.auth import hash_password

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        roles=user.get_role_names(),
        created_at=user.created_at,
        last_login=user.last_login,
    )


async def _load_all_users(db: AsyncSession) -> list[User]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User)
        .where(User.is_active == True)
        .options(
            selectinload(User.roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
        .order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.get("", response_model=list[UserOut])
async def list_users(
    current_user: User = Depends(require_permission(Perm.USER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    users = await _load_all_users(db)
    return [_user_out(u) for u in users]


@router.post("", response_model=UserOut)
async def create_user(
    data: UserCreate,
    current_user: User = Depends(require_permission(Perm.USER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    # Check username not taken
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Логин уже занят")

    # Validate role
    role_result = await db.execute(select(Role).where(Role.name == data.role_name))
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"Роль '{data.role_name}' не найдена")

    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль должен содержать не менее 8 символов")

    user = User(
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()

    user = await load_user_with_roles(user.id, db)
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: User = Depends(require_permission(Perm.USER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    user = await load_user_with_roles(user_id, db)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.username is not None:
        existing = await db.execute(select(User).where(User.username == data.username, User.id != user_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Логин уже занят")
        user.username = data.username
    if data.role_name is not None:
        role_result = await db.execute(select(Role).where(Role.name == data.role_name))
        role = role_result.scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=404, detail=f"Роль '{data.role_name}' не найдена")
        existing_roles = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
        for ur in existing_roles.scalars().all():
            await db.delete(ur)
        db.add(UserRole(user_id=user_id, role_id=role.id))
    if data.new_password is not None:
        if len(data.new_password) < 8:
            raise HTTPException(status_code=400, detail="Пароль должен содержать не менее 8 символов")
        user.password_hash = hash_password(data.new_password)
        user.must_change_password = False

    await db.commit()
    updated = await load_user_with_roles(user_id, db)
    return _user_out(updated)


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    current_user: User = Depends(require_permission(Perm.USER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    temp_password = secrets.token_urlsafe(8)
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    await db.commit()
    return {"temp_password": temp_password}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_permission(Perm.USER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")

    user = await load_user_with_roles(user_id, db)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if "admin" in user.get_role_names():
        admin_count = await db.execute(
            select(func.count())
            .select_from(UserRole)
            .join(Role)
            .where(Role.name == "admin", UserRole.user_id != user_id)
        )
        if admin_count.scalar() == 0:
            raise HTTPException(status_code=400, detail="Нельзя удалить последнего администратора")

    user.is_active = False
    user.username = f"__deleted_{user.id}_{user.username}"
    user.password_hash = ""
    await db.commit()
    return {"ok": True}
