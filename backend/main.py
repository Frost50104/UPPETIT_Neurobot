import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request as FastAPIRequest, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi.errors import RateLimitExceeded
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import get_settings
from database import engine, Base, AsyncSessionLocal, get_db

settings = get_settings()

from core.limiter import limiter

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def init_db():
    """Create all tables and seed default roles/permissions."""
    import models  # noqa: F401 — register all models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_roles_and_permissions(db)
        await seed_admin_user(db)


async def seed_roles_and_permissions(db: AsyncSession):
    from models.user import Role, Permission, RolePermission
    from core.rbac import ALL_PERMISSIONS, DEFAULT_ROLES

    for code, description in ALL_PERMISSIONS.items():
        result = await db.execute(select(Permission).where(Permission.code == code))
        if not result.scalar_one_or_none():
            db.add(Permission(code=code, description=description))
    await db.flush()

    for role_name, perm_codes in DEFAULT_ROLES.items():
        result = await db.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name=role_name, description=role_name.capitalize())
            db.add(role)
            await db.flush()

        for code in perm_codes:
            perm_result = await db.execute(select(Permission).where(Permission.code == code))
            perm = perm_result.scalar_one_or_none()
            if perm:
                rp_result = await db.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not rp_result.scalar_one_or_none():
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.commit()
    logger.info("Roles and permissions seeded.")


async def seed_admin_user(db: AsyncSession):
    from models.user import User, Role, UserRole
    from core.auth import hash_password
    from sqlalchemy.exc import IntegrityError

    result = await db.execute(select(User).where(User.username == "admin"))
    if result.scalar_one_or_none():
        return

    role_result = await db.execute(select(Role).where(Role.name == "admin"))
    role = role_result.scalar_one_or_none()
    if not role:
        return

    try:
        import secrets
        password = settings.admin_initial_password or secrets.token_urlsafe(16)
        admin = User(
            username="admin",
            full_name="Администратор",
            password_hash=hash_password(password),
            must_change_password=True,
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        db.add(UserRole(user_id=admin.id, role_id=role.id))
        await db.commit()
        if settings.admin_initial_password:
            logger.warning("Default admin user created with password from ADMIN_INITIAL_PASSWORD env — CHANGE IT!")
        else:
            logger.warning("Default admin user created with random password: %s — CHANGE IT IMMEDIATELY!", password)
    except IntegrityError:
        await db.rollback()


def _init_rag(app: FastAPI):
    """Initialize RAG components and store on app.state."""
    from openai import OpenAI
    from rag.vector_store import VectorStore
    from rag.rag_answerer import RAGAnswerer

    client = OpenAI(api_key=settings.openai_api_key)

    vector_store = VectorStore(
        storage_dir=settings.storage_dir,
        embedding_model=settings.embedding_model,
        openai_client=client,
    )
    vector_store.load()

    answerer = RAGAnswerer(
        vector_store=vector_store,
        openai_client=client,
        chat_model=settings.chat_model,
        top_k=settings.top_k,
        max_tokens=settings.max_tokens,
        min_score=settings.min_score,
        min_semantic_score=settings.min_semantic_score,
        query_rewrite=settings.query_rewrite,
    )

    app.state.openai_client = client
    app.state.vector_store = vector_store
    app.state.answerer = answerer
    logger.info("RAG pipeline initialized. Vector store ready: %s", vector_store.is_ready)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up... [env=%s]", settings.app_env)
    await init_db()

    os.makedirs(settings.storage_dir, exist_ok=True)
    os.makedirs(settings.images_dir, exist_ok=True)
    os.makedirs(settings.kb_downloads_dir, exist_ok=True)

    _init_rag(app)
    app.state.kb_rebuilding = False

    yield

    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title="Neurobot",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: FastAPIRequest, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте позже."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# API routers
from api.auth import router as auth_router
from api.chats import router as chats_router
from api.messages import router as messages_router
from api.admin.users import router as admin_users_router
from api.admin.kb import router as admin_kb_router
from api.feedback import router as feedback_router, stats_router as feedback_stats_router

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(feedback_router)
app.include_router(admin_users_router)
app.include_router(admin_kb_router)
app.include_router(feedback_stats_router)


# Public KB status (used by frontend to detect rebuild in progress)
@app.get("/api/kb-status", include_in_schema=False)
async def kb_status_public(request: FastAPIRequest):
    return {"rebuilding": getattr(request.app.state, "kb_rebuilding", False)}


# Read version from VERSION file (written by deploy.sh)
def _read_version(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"


def _read_frontend_version() -> str:
    import json
    path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist", "version.json")
    try:
        with open(path) as f:
            return json.load(f).get("version", "dev")
    except (FileNotFoundError, json.JSONDecodeError):
        return "dev"


BACKEND_VERSION = _read_version(os.path.join(os.path.dirname(__file__), "VERSION"))


# Public env info (used by frontend for staging badge + version display)
@app.get("/api/env", include_in_schema=False)
async def app_env():
    return {"env": settings.app_env, "backend": BACKEND_VERSION, "frontend": _read_frontend_version()}


# Health check for monitoring
@app.get("/api/health", include_in_schema=False)
async def health(request: FastAPIRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    await db.execute(text("SELECT 1"))
    vs_ready = getattr(request.app.state, "vector_store", None)
    return {
        "status": "ok",
        "db": True,
        "vs_ready": vs_ready.is_ready if vs_ready else False,
    }


# Serve KB images (authenticated)
@app.get("/api/kb-images/{filename}", include_in_schema=False)
async def serve_kb_image(filename: str, request: FastAPIRequest, db: AsyncSession = Depends(get_db)):
    from core.auth import get_current_user
    from fastapi import HTTPException
    await get_current_user(request=request, db=db)
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(settings.images_dir, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filepath)


# Serve React SPA — must be last
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    icons_dir = os.path.join(FRONTEND_DIST, "icons")
    if os.path.isdir(icons_dir):
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")

    fonts_dir = os.path.join(FRONTEND_DIST, "fonts")
    if os.path.isdir(fonts_dir):
        app.mount("/fonts", StaticFiles(directory=fonts_dir), name="fonts")

    @app.get("/sw.js", include_in_schema=False)
    async def serve_sw():
        return FileResponse(
            os.path.join(FRONTEND_DIST, "sw.js"),
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def serve_manifest():
        return FileResponse(
            os.path.join(FRONTEND_DIST, "manifest.webmanifest"),
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        # Try to serve static files first (favicon.ico, etc.)
        static_path = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(static_path):
            return FileResponse(static_path)
        index = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index)
