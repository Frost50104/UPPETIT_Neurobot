import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from database import get_db
from models.user import User, UserRole, Role, RolePermission, Permission
from schemas.auth import LoginRequest, ChangePasswordRequest, TokenResponse
from core.auth import (
    verify_password, hash_password, create_access_token, create_refresh_token,
    decode_token, get_current_active_user
)
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

COOKIE_OPTS = dict(httponly=True, secure=not settings.debug, samesite="lax")


def _user_query():
    return (
        select(User)
        .options(
            selectinload(User.roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
    )


async def _load_user(login: str, db: AsyncSession) -> User | None:
    result = await db.execute(_user_query().where(User.username == login))
    return result.scalar_one_or_none()


from core.limiter import limiter


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/5minutes")
async def login(request: Request, data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await _load_user(data.username, db)
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    response.set_cookie("access_token", access_token, max_age=settings.access_token_expire_minutes * 60, **COOKIE_OPTS)
    response.set_cookie("refresh_token", refresh_token, max_age=settings.refresh_token_expire_days * 86400, **COOKIE_OPTS)

    return TokenResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
        is_active=user.is_active,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=user.get_role_names(),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    from core.rbac import load_user_with_roles
    user = await load_user_with_roles(int(payload["sub"]), db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    response.set_cookie("access_token", access_token, max_age=settings.access_token_expire_minutes * 60, **COOKIE_OPTS)
    response.set_cookie("refresh_token", refresh_token, max_age=settings.refresh_token_expire_days * 86400, **COOKIE_OPTS)

    return TokenResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
        is_active=user.is_active,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=user.get_role_names(),
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.post("/change-password")
@limiter.limit("5/hour")
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный текущий пароль")

    current_user.password_hash = hash_password(data.new_password)
    current_user.must_change_password = False
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=TokenResponse)
async def me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from core.rbac import load_user_with_roles
    user = await load_user_with_roles(current_user.id, db)
    return TokenResponse(
        access_token="",
        must_change_password=user.must_change_password,
        is_active=user.is_active,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=user.get_role_names(),
    )
