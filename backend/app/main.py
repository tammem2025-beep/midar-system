from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import csv
import hashlib
import math
import io
import json
import logging
import os
import re
import secrets
from time import perf_counter
import traceback

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, delete, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from PIL import Image, UnidentifiedImageError

from .db import Base, engine, get_db
from .models import (AuthFailure, AuditLog, Campaign, Contact, Conversation, ExternalIdentity, IntegrationCredential, OAuthLoginGrant as GoogleLoginGrant, InstallationState, Membership, MediaAsset, Message, OAuthTransaction, Organization, Post, ShortVideoDraft, SocialAccount, Task, User, UserPreference)
from .schemas import (
    CampaignCreate, CampaignOut, CampaignUpdate, ChangePasswordIn, ContactCreate, ContactOut, ContactUpdate,
    ConversationCreate, ConversationOut, ConversationUpdate, LoginIn, MemberCreate, MemberOut, MemberUpdate,
    MediaAssetOut, MessageCreate, MessageOut, OrganizationOut, OrganizationUpdate, PostCreate, PostOut, PostUpdate,
    SetupIn, SetupStatusOut, SocialAccountCreate, SocialAccountOut, TaskCreate, TaskOut, TaskUpdate, TemporaryPasswordResetIn, TokenOut, UserOut, UserProfileUpdate, UserPreferencesOut, UserPreferencesUpdate, GoogleLoginCompleteIn, ShortVideoDraftCreate, ShortVideoDraftUpdate, ShortVideoDraftOut,
    TelegramDestinationVerifyIn, TelegramDeliveryResolveIn, PostReviewNoteIn,
)
from .security import TOKEN_TTL_SECONDS, create_access_token, decode_access_token, hash_password, verify_password
from .models import utcnow, new_id
from .integrations.telegram import TelegramAPIError, TelegramDeliveryUnknown, get_bot_info as telegram_get_bot_info, send_text as telegram_send_text, verify_channel as telegram_verify_channel
from .integrations.google_oidc import GoogleOIDCError, get_google_config, make_authorization_url as google_make_authorization_url, exchange_authorization_code as google_exchange_code, verify_google_id_token
from .integrations.authorization import (AuthorizationTransactionError, cleanup_expired_authorization_transactions, create_authorization_transaction, consume_authorization_transaction)
from .integrations.catalog import PROVIDER_REGISTRY, public_provider_catalog
from .integrations.registry import get_connector
from .integrations.meta_graph import (META_SCOPES, MetaDeliveryUnknown, MetaGraphError, access_token_for_account, exchange_meta_code, exchange_for_long_lived_token, fetch_account_media, get_meta_config, list_granted_permissions, list_managed_pages, make_meta_authorization_url, publish_page_text as meta_publish_page_text)
from .integrations.oauth_social import (SocialDeliveryUnknown, SocialOAuthError, exchange_and_identify, fetch_recent_content as fetch_social_recent_content, get_social_oauth_config, make_social_authorization_url, publish_text as publish_social_text)
from .integrations.credential_store import CredentialScopeError, CredentialStoreError, load_provider_credential, store_provider_credential
from .security_tokens import TokenVaultError
from .integrations.whatsapp_cloud import (WhatsAppCloudError, WhatsAppDeliveryUnknown, get_whatsapp_config, get_webhook_secrets as get_whatsapp_webhook_secrets, verify_webhook_signature, verify_business_number as whatsapp_verify_business_number, send_text as whatsapp_send_text)

API_PREFIX = "/api/v1"
security_logger = logging.getLogger("midar.security")
request_logger = logging.getLogger("midar.request")
SLOW_REQUEST_THRESHOLD_MS = 1500.0
# Source layout differs between a source checkout (project/backend/app) and the
# container image (project/app). Resolve the project root in both layouts.
_APP_PARENT = Path(__file__).resolve().parents[1]
# Packaged desktop builds set M_PROJECT_DIR to the install directory so static
# assets stay outside PyInstaller's temporary extraction folder.
_CONFIGURED_PROJECT_DIR = os.getenv("M_PROJECT_DIR", "").strip()
PROJECT_DIR = (
    Path(_CONFIGURED_PROJECT_DIR).expanduser().resolve()
    if _CONFIGURED_PROJECT_DIR
    else (_APP_PARENT.parent if _APP_PARENT.name == "backend" else _APP_PARENT)
)
FRONTEND_DIR = PROJECT_DIR / "frontend"
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(PROJECT_DIR / "data" / "media"))).resolve()
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_BYTES", str(100 * 1024 * 1024)))
LOGIN_WINDOW_MINUTES = int(os.getenv("LOGIN_WINDOW_MINUTES", "15"))
LOGIN_ACCOUNT_LIMIT = int(os.getenv("LOGIN_ACCOUNT_LIMIT", "10"))
LOGIN_IP_LIMIT = int(os.getenv("LOGIN_IP_LIMIT", "30"))

def env_flag(name: str, default: bool = False) -> bool:
    """Read an explicit boolean environment flag; false unless deliberately enabled."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def prepare_local_schema():
    """Convenience schema preparation for local/test runs; production uses Alembic migrations."""
    Base.metadata.create_all(bind=engine)
    # create_all intentionally does not alter tables from the early 0.2.x preview.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("users")}
        with engine.begin() as connection:
            if "must_change_password" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE"))
            if "auth_version" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0"))
    # Keep pre-migration local SQLite databases compatible in development mode.
    # Production deployments use the reviewed Alembic migrations instead.
    if "posts" in inspector.get_table_names():
        post_columns = {column["name"] for column in inspector.get_columns("posts")}
        with engine.begin() as connection:
            if "social_account_id" not in post_columns:
                connection.execute(text("ALTER TABLE posts ADD COLUMN social_account_id VARCHAR(36) NULL"))
            if "published_at" not in post_columns:
                connection.execute(text("ALTER TABLE posts ADD COLUMN published_at DATETIME NULL"))
            if "provider_post_id" not in post_columns:
                connection.execute(text("ALTER TABLE posts ADD COLUMN provider_post_id VARCHAR(180) NULL"))
            if "publish_error" not in post_columns:
                connection.execute(text("ALTER TABLE posts ADD COLUMN publish_error TEXT NULL"))
        from sqlalchemy import inspect as sa_inspect
        post_indexes = {index["name"] for index in sa_inspect(engine).get_indexes("posts")}
        if "ix_posts_social_account_id" not in post_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX ix_posts_social_account_id ON posts (social_account_id)"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ready = False
    if os.getenv("APP_ENV", "development").lower() in {"development", "test"}:
        prepare_local_schema()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    app.state.ready = True
    yield


app = FastAPI(
    title="M API",
    description="M API — Manage. Connect. Grow. يتضمن تسجيل Google الاختياري وقراءة محتوى Facebook Pages وحسابات Instagram الاحترافية بعد إعداد OAuth.",
    version="0.24.0",
    lifespan=lifespan,
)

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

def _safe_observability_value(value: str, limit: int = 256) -> str:
    """Keep control characters out of request logs without recording query strings."""
    return "".join(char if char.isprintable() and char not in "\r\n\t" else "?" for char in str(value))[:limit]


def _request_log_path(request: Request) -> str:
    # Log only a framework route template. For unmatched requests, never fall back
    # to the raw path because applications sometimes put identifiers or secrets in it.
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "<unmatched-route>"
    return _safe_observability_value(template, 256)


@app.middleware("http")
async def security_headers(request, call_next):
    # A server-generated correlation id makes failures diagnosable without trusting
    # arbitrary client-supplied ids or logging request bodies, query strings, cookies,
    # Authorization headers, OAuth codes, or provider tokens.
    request_id = secrets.token_hex(16)
    request.state.request_id = request_id
    started = perf_counter()
    request_failed = False
    safe_method = _safe_observability_value(request.method, 16)

    try:
        response = await call_next(request)
    except Exception as exc:
        request_failed = True
        duration_ms = (perf_counter() - started) * 1000
        # Log traceback frames for diagnosis, but not the exception message, which
        # can accidentally contain third-party response data or secrets.
        stack = " | ".join(
            f"{frame.filename}:{frame.lineno}:{frame.name}"
            for frame in traceback.extract_tb(exc.__traceback__)
        )[-8000:]
        request_logger.error(
            "request_unhandled_exception request_id=%s method=%s path=%s duration_ms=%.1f exception_type=%s stack=%r",
            request_id, safe_method, _request_log_path(request), duration_ms, type(exc).__name__, stack,
        )
        response = JSONResponse(
            status_code=500,
            content={
                "detail": "حدث خطأ داخلي. يرجى تزويد الدعم بمعرّف الطلب.",
                "request_id": request_id,
            },
        )

    duration_ms = (perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"

    if not request_failed and (response.status_code >= 500 or duration_ms >= SLOW_REQUEST_THRESHOLD_MS):
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING
        request_logger.log(
            level,
            "request_observed request_id=%s method=%s path=%s status_code=%d duration_ms=%.1f",
            request_id, safe_method, _request_log_path(request), response.status_code, duration_ms,
        )
    return response

bearer = HTTPBearer(auto_error=False)

class AuthContext:
    def __init__(self, user: User, membership: Membership, organization: Organization):
        self.user = user
        self.membership = membership
        self.organization = organization


def get_context(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer), db: Session = Depends(get_db)) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="يلزم تسجيل الدخول", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة أو منتهية؛ سجّل الدخول مجددًا", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, payload["sub"])
    membership = db.scalar(select(Membership).where(Membership.user_id == payload["sub"], Membership.organization_id == payload["org"]))
    organization = db.get(Organization, payload["org"])
    if not user or not user.is_active or not membership or not organization:
        raise HTTPException(status_code=401, detail="الحساب أو مساحة العمل غير متاحين")
    if int(payload.get("ver", 0)) != int(user.auth_version or 0):
        raise HTTPException(status_code=401, detail="تم إلغاء هذه الجلسة؛ سجّل الدخول مجددًا", headers={"WWW-Authenticate": "Bearer"})
    if user.must_change_password and request.url.path not in {f"{API_PREFIX}/auth/me", f"{API_PREFIX}/auth/change-password", f"{API_PREFIX}/auth/logout"}:
        raise HTTPException(status_code=403, detail="يجب تغيير كلمة المرور المؤقتة قبل استخدام النظام")
    return AuthContext(user, membership, organization)


# Permissions are enforced on the API, not merely by hiding UI controls.
ALL_AREAS = {"posts", "contacts", "tasks", "accounts", "team", "settings", "media", "inbox", "campaigns", "audit"}
ROLE_READ_PERMISSIONS = {
    "owner": ALL_AREAS,
    "admin": ALL_AREAS,
    "editor": {"posts", "tasks", "accounts", "media", "campaigns"},
    "support": {"contacts", "tasks", "accounts", "inbox"},
    "analyst": {"posts", "contacts", "tasks", "accounts", "campaigns"},
}
ROLE_PERMISSIONS = {
    "owner": ALL_AREAS,
    "admin": ALL_AREAS,
    "editor": {"posts", "tasks", "media", "campaigns"},
    "support": {"contacts", "tasks", "inbox"},
    "analyst": set(),
}


def require_read(ctx: AuthContext, area: str):
    if area not in ROLE_READ_PERMISSIONS.get(ctx.membership.role, set()):
        raise HTTPException(status_code=403, detail="لا تملك صلاحية الاطلاع على هذا القسم")


def require_write(ctx: AuthContext, area: str = "general"):
    if area not in ROLE_PERMISSIONS.get(ctx.membership.role, set()):
        raise HTTPException(status_code=403, detail="لا تملك الصلاحية لتنفيذ هذا الإجراء")


def require_roles(ctx: AuthContext, roles: set[str]):
    if ctx.membership.role not in roles:
        raise HTTPException(status_code=403, detail="هذه العملية متاحة لمدير مساحة العمل فقط")


def audit(db: Session, ctx: AuthContext, action: str, entity_type: str, entity_id: str | None = None, details: dict[str, Any] | None = None):
    db.add(AuditLog(organization_id=ctx.organization.id, user_id=ctx.user.id, action=action, entity_type=entity_type, entity_id=entity_id, details=json.dumps(details or {}, ensure_ascii=False)))


def latest_post_review_notes(db: Session, organization_id: str, post_ids: list[str]) -> dict[str, str]:
    """Fetch the latest change-request note for posts using one bounded query.

    The note is stored in the existing audit log, avoiding a DB migration while
    making feedback available to authors who cannot read the admin-only audit page.
    """
    if not post_ids:
        return {}
    rows = db.execute(
        select(AuditLog.entity_id, AuditLog.details)
        .where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type == "post",
            AuditLog.action == "post.changes_requested",
            AuditLog.entity_id.in_(post_ids),
        )
        .order_by(AuditLog.created_at.desc())
    ).all()
    result: dict[str, str] = {}
    for entity_id, raw_details in rows:
        if not entity_id or entity_id in result:
            continue
        try:
            details = json.loads(raw_details or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        note = details.get("note") if isinstance(details, dict) else None
        if isinstance(note, str) and note.strip():
            result[entity_id] = note.strip()
    return result


def user_out(ctx: AuthContext) -> dict[str, Any]:
    return {
        "id": ctx.user.id,
        "email": ctx.user.email,
        "full_name": ctx.user.full_name,
        "role": ctx.membership.role,
        "organization_id": ctx.organization.id,
        "organization_name": ctx.organization.name,
        "must_change_password": bool(ctx.user.must_change_password),
    }


def rate_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def login_keys(email: str, ip: str) -> tuple[str, str]:
    return rate_key(f"account|{email}"), rate_key(f"ip|{ip}")


def _login_throttle_wait_seconds(db: Session, key_hash: str, count: int, limit: int, cutoff: datetime) -> int:
    # Find the failure whose expiration will bring the rolling count below its
    # limit. A fixed full-window Retry-After unnecessarily locks out users whose
    # oldest failures are already close to expiring.
    offset = max(0, count - limit)
    oldest_needed = db.scalar(
        select(AuthFailure.created_at)
        .where(AuthFailure.key_hash == key_hash, AuthFailure.created_at >= cutoff)
        .order_by(AuthFailure.created_at.asc())
        .offset(offset)
        .limit(1)
    )
    if oldest_needed is None:
        return 1
    if oldest_needed.tzinfo is None:
        oldest_needed = oldest_needed.replace(tzinfo=timezone.utc)
    expires_at = oldest_needed + timedelta(minutes=LOGIN_WINDOW_MINUTES)
    return max(1, math.ceil((expires_at - utcnow()).total_seconds()))


def check_login_throttle(db: Session, account_key: str, ip_key: str):
    cutoff = utcnow() - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    account_count = db.scalar(select(func.count(AuthFailure.id)).where(AuthFailure.key_hash == account_key, AuthFailure.created_at >= cutoff)) or 0
    ip_count = db.scalar(select(func.count(AuthFailure.id)).where(AuthFailure.key_hash == ip_key, AuthFailure.created_at >= cutoff)) or 0
    waits = []
    if account_count >= LOGIN_ACCOUNT_LIMIT:
        waits.append(_login_throttle_wait_seconds(db, account_key, account_count, LOGIN_ACCOUNT_LIMIT, cutoff))
    if ip_count >= LOGIN_IP_LIMIT:
        waits.append(_login_throttle_wait_seconds(db, ip_key, ip_count, LOGIN_IP_LIMIT, cutoff))
    if waits:
        retry_after = max(waits)
        wait_minutes = max(1, math.ceil(retry_after / 60))
        raise HTTPException(
            status_code=429,
            detail=f"محاولات دخول كثيرة. حاول بعد {wait_minutes} دقيقة.",
            headers={"Retry-After": str(retry_after)},
        )


def record_login_failure(db: Session, account_key: str, ip_key: str):
    db.add_all([AuthFailure(key_hash=account_key), AuthFailure(key_hash=ip_key)])
    db.execute(delete(AuthFailure).where(AuthFailure.created_at < utcnow() - timedelta(days=1)))
    db.commit()


def clear_login_failures(db: Session, account_key: str):
    db.execute(delete(AuthFailure).where(AuthFailure.key_hash == account_key))


def not_found(entity: str):
    raise HTTPException(status_code=404, detail=f"{entity} غير موجود")

@app.get("/api/v1/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(select(1)).scalar_one()
        db_state = "ok"
    except Exception:
        db_state = "unavailable"
    response = {"status": "ok" if db_state == "ok" else "degraded", "service": "m-api", "version": app.version, "database": db_state}
    if db_state != "ok":
        raise HTTPException(status_code=503, detail=response)
    return response


@app.get(f"{API_PREFIX}/auth/status", response_model=SetupStatusOut)
def auth_status(db: Session = Depends(get_db)):
    return {"setup_required": (db.scalar(select(func.count(Organization.id))) or 0) == 0}


@app.post(f"{API_PREFIX}/auth/setup", response_model=TokenOut, status_code=201)
def setup(data: SetupIn, db: Session = Depends(get_db)):
    # One-time installation row closes the race between two simultaneous initial setup requests.
    if (db.scalar(select(func.count(Organization.id))) or 0) > 0 or db.get(InstallationState, "primary"):
        raise HTTPException(status_code=409, detail="تم إعداد المنصة بالفعل. سجّل الدخول أو استخدم دعوة مدير النظام.")
    lock = InstallationState(id="primary")
    db.add(lock)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="تم إعداد المنصة بالفعل. سجّل الدخول.") from exc
    email = str(data.email).lower().strip()
    org = Organization(name=data.organization_name.strip(), timezone=data.timezone.strip())
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password))
    db.add(org)
    db.flush()
    db.add(user)
    db.flush()
    membership = Membership(organization_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    lock.organization_id = org.id
    db.add(AuditLog(organization_id=org.id, user_id=user.id, action="setup.created", entity_type="organization", entity_id=org.id, details="{}"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="تعذر إتمام الإعداد؛ تحقق من البريد الإلكتروني وحالة النظام.") from exc
    db.refresh(user); db.refresh(org); db.refresh(membership)
    ctx = AuthContext(user, membership, org)
    return {"access_token": create_access_token(user.id, org.id, user.auth_version), "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS, "user": user_out(ctx)}


@app.post(f"{API_PREFIX}/auth/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = str(data.email).lower().strip()
    ip = request.client.host if request.client else "unknown"
    account_key, ip_key = login_keys(email, ip)
    check_login_throttle(db, account_key, ip_key)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        record_login_failure(db, account_key, ip_key)
        raise HTTPException(status_code=401, detail="البريد الإلكتروني أو كلمة المرور غير صحيحة")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at.asc()))
    if not membership:
        raise HTTPException(status_code=403, detail="هذا الحساب غير مرتبط بمساحة عمل")
    org = db.get(Organization, membership.organization_id)
    if not org:
        raise HTTPException(status_code=403, detail="مساحة العمل غير موجودة")
    clear_login_failures(db, account_key)
    ctx = AuthContext(user, membership, org)
    audit(db, ctx, "auth.login", "user", user.id)
    db.commit()
    return {"access_token": create_access_token(user.id, org.id, user.auth_version), "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS, "user": user_out(ctx)}


@app.get(f"{API_PREFIX}/auth/me", response_model=UserOut)
def me(ctx: AuthContext = Depends(get_context)):
    return user_out(ctx)


@app.patch(f"{API_PREFIX}/auth/profile", response_model=UserOut)
def update_profile(data: UserProfileUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Update editable profile fields. Email changes are deliberately excluded until email verification exists."""
    ctx.user.full_name = data.full_name.strip()
    audit(db, ctx, "auth.profile_updated", "user", ctx.user.id, {"fields": ["full_name"]})
    db.commit()
    db.refresh(ctx.user)
    return user_out(ctx)


def _preference_values(row: UserPreference | None) -> dict[str, str]:
    return {
        "theme_mode": row.theme_mode if row else "dark",
        "accent_color": row.accent_color if row else "blue",
        "density": row.density if row else "comfortable",
    }


@app.get(f"{API_PREFIX}/preferences", response_model=UserPreferencesOut)
def get_preferences(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    row = db.get(UserPreference, ctx.user.id)
    return _preference_values(row)


@app.patch(f"{API_PREFIX}/preferences", response_model=UserPreferencesOut)
def update_preferences(data: UserPreferencesUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    row = db.get(UserPreference, ctx.user.id)
    if row is None:
        row = UserPreference(user_id=ctx.user.id)
        db.add(row)
    for key, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    audit(db, ctx, "preferences.updated", "user_preference", ctx.user.id, data.model_dump(exclude_unset=True, exclude_none=True))
    db.commit()
    db.refresh(row)
    return _preference_values(row)


def _google_binding_cookie_name(raw_state: str) -> str:
    """Bind each OAuth transaction to a browser cookie without exposing state in cookie names."""
    digest = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()[:24]
    return f"midar_google_bind_{digest}"


def _google_cookie_secure(request: Request) -> bool:
    # Production must always use Secure; local HTTP development remains usable.
    return os.getenv("APP_ENV", "development").lower() == "production" or request.url.scheme == "https"


def _clear_google_binding_cookie(response: RedirectResponse, cookie_name: str | None, secure: bool) -> None:
    if cookie_name:
        response.delete_cookie(
            key=cookie_name, path=f"{API_PREFIX}/auth/google/callback", secure=secure,
            httponly=True, samesite="lax",
        )


def _safe_google_redirect(
    result: str, *, cookie_name: str | None = None, secure_cookie: bool = False,
) -> RedirectResponse:
    # Only fixed result codes are accepted here; no arbitrary destination can be supplied.
    allowed = {"not_configured", "access_denied", "invalid_state", "exchange_failed", "identity_unlinked", "account_inactive", "link_conflict", "link_stale", "link_success", "not_linked", "login_success", "invalid_profile", "setup_complete"}
    safe_result = result if result in allowed else "invalid_state"
    target = f"/#google_result={safe_result}"
    response = RedirectResponse(url=target, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    _clear_google_binding_cookie(response, cookie_name, secure_cookie)
    return response


def _begin_google_transaction(db: Session, purpose: str, ctx: AuthContext | None = None) -> tuple[str, str, str]:
    """Use the common OAuth transaction service for Google identity flows too."""
    config = get_google_config()
    if not config:
        raise HTTPException(status_code=503, detail="تسجيل Google غير مهيأ. أضف إعدادات OAuth إلى ملف .env أولًا.")
    now = utcnow()
    cleanup_expired_authorization_transactions(db)
    db.execute(delete(GoogleLoginGrant).where(GoogleLoginGrant.expires_at < now))
    try:
        challenge = create_authorization_transaction(
            db,
            provider="google",
            # Google OIDC links a user's own sign-in identity, not a workspace social
            # publishing account. Keep that distinct from admin-only provider linking.
            purpose="identity_link" if purpose == "link" else purpose,
            user_id=ctx.user.id if ctx else None,
            organization_id=ctx.organization.id if ctx else None,
            auth_version=int(ctx.user.auth_version or 0) if ctx else None,
            ttl_seconds=600,
        )
    except AuthorizationTransactionError as exc:
        db.rollback()
        status = 403 if exc.reason in {"insufficient_role", "invalid_context", "auth_changed"} else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    db.commit()
    authorization_url = google_make_authorization_url(
        config, challenge.state, challenge.nonce, challenge.code_challenge,
    )
    return authorization_url, challenge.state, challenge.browser_binding


@app.get(f"{API_PREFIX}/auth/google/config")
def google_auth_config():
    config = get_google_config()
    return {"enabled": bool(config), "provider": "Google", "scopes": ["openid", "email", "profile"], "message": None if config else "تسجيل Google غير مهيأ على هذا الخادم."}


def _google_authorization_start_response(
    request: Request, purpose: str, ctx: AuthContext | None, db: Session,
) -> JSONResponse:
    authorization_url, state, browser_binding = _begin_google_transaction(db, purpose, ctx)
    cookie_name = _google_binding_cookie_name(state)
    response = JSONResponse({"authorization_url": authorization_url})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        key=cookie_name, value=browser_binding, max_age=600,
        path=f"{API_PREFIX}/auth/google/callback", secure=_google_cookie_secure(request),
        httponly=True, samesite="lax",
    )
    return response


@app.post(f"{API_PREFIX}/auth/google/login-url")
def google_login_url(request: Request, db: Session = Depends(get_db)):
    return _google_authorization_start_response(request, "login", None, db)


@app.post(f"{API_PREFIX}/auth/google/setup-url")
def google_setup_url(request: Request, db: Session = Depends(get_db)):
    """Allow Google to create the first owner workspace once only."""
    if (db.scalar(select(func.count(Organization.id))) or 0) > 0 or db.get(InstallationState, "primary"):
        raise HTTPException(status_code=409, detail="تم إعداد مساحة العمل بالفعل. سجّل الدخول بالطريقة المرتبطة بحسابك.")
    return _google_authorization_start_response(request, "setup", None, db)


@app.post(f"{API_PREFIX}/auth/google/link-url")
def google_link_url(request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    return _google_authorization_start_response(request, "link", ctx, db)


@app.get(f"{API_PREFIX}/auth/google/status")
def google_link_status(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == ctx.user.id, ExternalIdentity.provider == "google"))
    return {"enabled": bool(get_google_config()), "linked": bool(identity), "email": identity.email if identity else None}


@app.get(f"{API_PREFIX}/auth/google/callback")
def google_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: Session = Depends(get_db),
):
    if not state or len(state) > 256:
        security_logger.warning("oauth_callback_rejected provider=google reason=missing_or_oversize_state")
        return _safe_google_redirect("invalid_state")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    cookie_name = _google_binding_cookie_name(state)
    secure_cookie = _google_cookie_secure(request)
    # Read the stored purpose only to select the expected transaction type. The
    # shared service performs all validation, expiry checks, browser binding, and
    # one-time consumption before any external network request.
    stored_transaction = db.get(OAuthTransaction, state_hash)
    purpose = stored_transaction.purpose if stored_transaction else "login"
    browser_cookie = request.cookies.get(cookie_name, "")
    try:
        consumed = consume_authorization_transaction(
            db,
            provider="google",
            purpose=purpose,
            state=state,
            browser_binding=browser_cookie,
        )
        db.commit()  # Commit single-use state before network I/O.
    except AuthorizationTransactionError as exc:
        if exc.cleanup_performed:
            db.commit()
        else:
            db.rollback()
        security_logger.warning("oauth_callback_rejected provider=google reason=%s", exc.reason)
        return _safe_google_redirect("invalid_state", cookie_name=cookie_name, secure_cookie=secure_cookie)

    tx = {
        "purpose": consumed.purpose,
        "nonce": consumed.nonce,
        "code_verifier": consumed.code_verifier,
        "user_id": consumed.user_id,
        "organization_id": consumed.organization_id,
        "auth_version": consumed.auth_version,
    }
    security_logger.info("oauth_callback_state_consumed provider=google purpose=%s", tx["purpose"])

    if error:
        # A provider error still consumes a valid transaction; it cannot be replayed.
        security_logger.info("oauth_callback_cancelled provider=google purpose=%s", tx["purpose"])
        return _safe_google_redirect("access_denied", cookie_name=cookie_name, secure_cookie=secure_cookie)
    if not code or len(code) > 4096:
        return _safe_google_redirect("invalid_state", cookie_name=cookie_name, secure_cookie=secure_cookie)
    config = get_google_config()
    if not config:
        return _safe_google_redirect("not_configured", cookie_name=cookie_name, secure_cookie=secure_cookie)
    try:
        token = google_exchange_code(config, code, tx["code_verifier"])
        claims = verify_google_id_token(token, config["client_id"], tx["nonce"])
    except GoogleOIDCError:
        security_logger.warning("oauth_provider_exchange_failed provider=google purpose=%s", tx["purpose"])
        return _safe_google_redirect("exchange_failed", cookie_name=cookie_name, secure_cookie=secure_cookie)

    provider_subject = claims["sub"]
    email = str(claims["email"]).strip().lower()
    if tx["purpose"] == "setup":
        # Only an empty installation can be initialized using a Google-verified identity.
        if (db.scalar(select(func.count(Organization.id))) or 0) > 0 or db.get(InstallationState, "primary"):
            return _safe_google_redirect("setup_complete", cookie_name=cookie_name, secure_cookie=secure_cookie)
        if db.scalar(select(User).where(User.email == email)) or db.scalar(select(ExternalIdentity).where(
            ExternalIdentity.provider == "google", ExternalIdentity.subject == provider_subject,
        )):
            return _safe_google_redirect("account_inactive", cookie_name=cookie_name, secure_cookie=secure_cookie)
        lock = InstallationState(id="primary")
        db.add(lock)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _safe_google_redirect("setup_complete", cookie_name=cookie_name, secure_cookie=secure_cookie)
        full_name = str(claims.get("name") or email.split("@", 1)[0]).strip()[:160]
        if len(full_name) < 2:
            full_name = "M Owner"
        organization = Organization(name=f"مساحة عمل {full_name}"[:160], timezone="Asia/Hebron")
        db.add(organization)
        db.flush()
        user = User(email=email, full_name=full_name, password_hash=hash_password(secrets.token_urlsafe(48)))
        db.add(user)
        db.flush()
        membership = Membership(organization_id=organization.id, user_id=user.id, role="owner")
        db.add(membership)
        identity = ExternalIdentity(
            user_id=user.id, provider="google", subject=provider_subject, email=email,
            email_verified=True, created_at=utcnow(), last_login_at=utcnow(),
        )
        db.add(identity)
        lock.organization_id = organization.id
        db.add(AuditLog(
            organization_id=organization.id, user_id=user.id, action="setup.google_created",
            entity_type="organization", entity_id=organization.id, details='{"provider":"google"}',
        ))
        one_time_code = secrets.token_urlsafe(48)
        db.add(GoogleLoginGrant(
            code_hash=hashlib.sha256(one_time_code.encode("utf-8")).hexdigest(),
            user_id=user.id, organization_id=organization.id, auth_version=int(user.auth_version or 0),
            created_at=utcnow(), expires_at=utcnow() + timedelta(minutes=2), used_at=None,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return _safe_google_redirect("setup_complete", cookie_name=cookie_name, secure_cookie=secure_cookie)
        response = RedirectResponse(url=f"/#google_code={one_time_code}", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        _clear_google_binding_cookie(response, cookie_name, secure_cookie)
        return response

    if tx["purpose"] in {"link", "identity_link"}:
        user = db.get(User, tx["user_id"]) if tx["user_id"] else None
        organization = db.get(Organization, tx["organization_id"]) if tx["organization_id"] else None
        membership = db.scalar(select(Membership).where(Membership.user_id == tx["user_id"], Membership.organization_id == tx["organization_id"])) if user and organization else None
        if not user or not organization or not membership or not user.is_active or int(user.auth_version or 0) != int(tx["auth_version"] or 0):
            return _safe_google_redirect("link_stale", cookie_name=cookie_name, secure_cookie=secure_cookie)
        identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == "google", ExternalIdentity.subject == provider_subject))
        user_identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == "google", ExternalIdentity.user_id == user.id))
        if identity and identity.user_id != user.id:
            return _safe_google_redirect("link_conflict", cookie_name=cookie_name, secure_cookie=secure_cookie)
        if user_identity and user_identity.subject != provider_subject:
            return _safe_google_redirect("link_conflict", cookie_name=cookie_name, secure_cookie=secure_cookie)
        if not identity:
            identity = ExternalIdentity(user_id=user.id, provider="google", subject=provider_subject, email=email, email_verified=True, created_at=utcnow())
            db.add(identity)
        identity.email = email
        identity.email_verified = True
        audit(db, AuthContext(user, membership, organization), "auth.google_linked", "external_identity", identity.id, {"provider": "google"})
        db.commit()
        return _safe_google_redirect("link_success", cookie_name=cookie_name, secure_cookie=secure_cookie)

    if tx["purpose"] != "login":
        return _safe_google_redirect("invalid_state", cookie_name=cookie_name, secure_cookie=secure_cookie)
    identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == "google", ExternalIdentity.subject == provider_subject))
    if not identity:
        # Never auto-link by email: the user must first authenticate locally and explicitly link Google.
        return _safe_google_redirect("not_linked", cookie_name=cookie_name, secure_cookie=secure_cookie)
    user = db.get(User, identity.user_id)
    if not user or not user.is_active:
        return _safe_google_redirect("account_inactive", cookie_name=cookie_name, secure_cookie=secure_cookie)
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at.asc()))
    if not membership or not db.get(Organization, membership.organization_id):
        return _safe_google_redirect("account_inactive", cookie_name=cookie_name, secure_cookie=secure_cookie)
    one_time_code = secrets.token_urlsafe(48)
    db.add(GoogleLoginGrant(
        code_hash=hashlib.sha256(one_time_code.encode("utf-8")).hexdigest(), user_id=user.id,
        organization_id=membership.organization_id, auth_version=int(user.auth_version or 0),
        created_at=utcnow(), expires_at=utcnow() + timedelta(minutes=2), used_at=None,
    ))
    identity.last_login_at = utcnow()
    db.commit()
    response = RedirectResponse(url=f"/#google_code={one_time_code}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    _clear_google_binding_cookie(response, cookie_name, secure_cookie)
    return response


@app.post(f"{API_PREFIX}/auth/google/complete", response_model=TokenOut)
def complete_google_login(data: GoogleLoginCompleteIn, db: Session = Depends(get_db)):
    now = utcnow()
    code_hash = hashlib.sha256(data.code.encode("utf-8")).hexdigest()
    grant = db.scalar(select(GoogleLoginGrant).where(GoogleLoginGrant.code_hash == code_hash, GoogleLoginGrant.used_at.is_(None), GoogleLoginGrant.expires_at > now))
    if not grant:
        raise HTTPException(status_code=401, detail="انتهت صلاحية محاولة تسجيل Google أو استُخدمت مسبقًا. ابدأ من جديد.")
    user = db.get(User, grant.user_id)
    organization = db.get(Organization, grant.organization_id)
    membership = db.scalar(select(Membership).where(Membership.user_id == grant.user_id, Membership.organization_id == grant.organization_id))
    if not user or not user.is_active or not organization or not membership or int(user.auth_version or 0) != int(grant.auth_version):
        raise HTTPException(status_code=401, detail="لم يعد الحساب صالحًا لتسجيل الدخول. استخدم طريقة الدخول البديلة.")
    consumed = db.execute(update(GoogleLoginGrant).where(GoogleLoginGrant.code_hash == code_hash, GoogleLoginGrant.used_at.is_(None), GoogleLoginGrant.expires_at > now).values(used_at=now))
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="تم استخدام محاولة تسجيل Google مسبقًا.")
    ctx = AuthContext(user, membership, organization)
    audit(db, ctx, "auth.google_login", "user", user.id, {"provider": "google"})
    db.commit()
    return {"access_token": create_access_token(user.id, organization.id, user.auth_version), "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS, "user": user_out(ctx)}


@app.post(f"{API_PREFIX}/auth/change-password", response_model=TokenOut)
def change_password(data: ChangePasswordIn, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=422, detail="اختر كلمة مرور مختلفة عن الحالية")
    ctx.user.password_hash = hash_password(data.new_password)
    ctx.user.must_change_password = False
    ctx.user.auth_version = int(ctx.user.auth_version or 0) + 1
    audit(db, ctx, "auth.password_changed", "user", ctx.user.id)
    db.commit()
    db.refresh(ctx.user)
    return {"access_token": create_access_token(ctx.user.id, ctx.organization.id, ctx.user.auth_version), "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS, "user": user_out(ctx)}


@app.post(f"{API_PREFIX}/auth/logout", status_code=204)
def logout(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    # Version-based revocation invalidates all tokens issued to this user.
    ctx.user.auth_version = int(ctx.user.auth_version or 0) + 1
    audit(db, ctx, "auth.logout", "user", ctx.user.id)
    db.commit()
    return Response(status_code=204)


@app.get(f"{API_PREFIX}/organization", response_model=OrganizationOut)
def get_organization(ctx: AuthContext = Depends(get_context)):
    return ctx.organization


@app.patch(f"{API_PREFIX}/organization", response_model=OrganizationOut)
def update_organization(data: OrganizationUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    ctx.organization.name = data.name.strip()
    ctx.organization.timezone = data.timezone
    audit(db, ctx, "updated", "organization", ctx.organization.id, {"timezone": data.timezone})
    db.commit()
    db.refresh(ctx.organization)
    return ctx.organization


@app.get(f"{API_PREFIX}/team/members", response_model=list[MemberOut])
def list_team_members(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    stmt = select(User, Membership).join(Membership, Membership.user_id == User.id).where(Membership.organization_id == ctx.organization.id).order_by(Membership.created_at.asc())
    return [{"id": user.id, "email": user.email, "full_name": user.full_name, "role": membership.role, "is_active": user.is_active, "must_change_password": user.must_change_password, "created_at": user.created_at} for user, membership in db.execute(stmt).all()]


@app.post(f"{API_PREFIX}/team/members", response_model=MemberOut, status_code=201)
def create_team_member(data: MemberCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    if ctx.membership.role == "admin" and data.role == "admin":
        raise HTTPException(status_code=403, detail="مدير النظام فقط يستطيع تعيين مدير آخر")
    email = str(data.email).lower().strip()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="يوجد حساب بهذا البريد الإلكتروني بالفعل")
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.temporary_password), must_change_password=True)
    db.add(user)
    try:
        db.flush()
        membership = Membership(organization_id=ctx.organization.id, user_id=user.id, role=data.role)
        db.add(membership)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="تعذر إنشاء عضو الفريق؛ تحقق من البريد الإلكتروني.") from exc
    audit(db, ctx, "created", "team_member", user.id, {"role": data.role})
    db.commit()
    db.refresh(user); db.refresh(membership)
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": membership.role, "is_active": user.is_active, "must_change_password": user.must_change_password, "created_at": user.created_at}


@app.patch(f"{API_PREFIX}/team/members/{{member_id}}", response_model=MemberOut)
def update_team_member(member_id: str, data: MemberUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    membership = db.scalar(select(Membership).where(Membership.user_id == member_id, Membership.organization_id == ctx.organization.id))
    user = db.get(User, member_id)
    if not membership or not user:
        not_found("عضو الفريق")
    if membership.role == "owner":
        raise HTTPException(status_code=403, detail="لا يمكن تغيير صلاحيات مالك مساحة العمل من هذه الشاشة")
    if ctx.membership.role == "admin" and membership.role == "admin":
        raise HTTPException(status_code=403, detail="لا يمكن للمدير تعديل حساب مدير آخر")
    if member_id == ctx.user.id and data.is_active is False:
        raise HTTPException(status_code=400, detail="لا يمكنك تعطيل حسابك بنفسك")
    if ctx.membership.role == "admin" and data.role == "admin":
        raise HTTPException(status_code=403, detail="مدير النظام فقط يستطيع تعيين مدير آخر")
    if data.role is not None:
        membership.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
        user.auth_version = int(user.auth_version or 0) + 1
    audit(db, ctx, "updated", "team_member", user.id, {"role": membership.role, "is_active": user.is_active})
    db.commit()
    db.refresh(user); db.refresh(membership)
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": membership.role, "is_active": user.is_active, "must_change_password": user.must_change_password, "created_at": user.created_at}


@app.post(f"{API_PREFIX}/team/members/{{member_id}}/reset-password", status_code=204)
def reset_team_member_password(member_id: str, data: TemporaryPasswordResetIn, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    membership = db.scalar(select(Membership).where(Membership.user_id == member_id, Membership.organization_id == ctx.organization.id))
    user = db.get(User, member_id)
    if not membership or not user:
        not_found("عضو الفريق")
    if membership.role == "owner":
        raise HTTPException(status_code=403, detail="لا يمكن إعادة ضبط كلمة مرور المالك من هذه الشاشة")
    if ctx.membership.role == "admin" and membership.role == "admin":
        raise HTTPException(status_code=403, detail="مدير النظام فقط يستطيع إدارة حساب مدير آخر")
    user.password_hash = hash_password(data.temporary_password)
    user.must_change_password = True
    user.auth_version = int(user.auth_version or 0) + 1
    audit(db, ctx, "team_member.password_reset", "team_member", user.id)
    db.commit()
    return Response(status_code=204)


@app.get(f"{API_PREFIX}/integrations/catalog")
def integration_catalog(ctx: AuthContext = Depends(get_context)):
    """Return a truthful, non-secret capability catalog for the social connectors."""
    require_read(ctx, "accounts")
    return {
        "release": app.version,
        "providers": public_provider_catalog(),
        "notice": "التسجيل في الكتالوج لا يعني أن الحساب متصل؛ الوظائف الخارجية تحتاج موصلًا منفذًا وإعدادًا وتحققًا فعليًا.",
    }


@app.get(f"{API_PREFIX}/integrations/status")
def integration_status(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    # Presence of credentials is not proof of a completed OAuth flow or a verified account.
    providers = []
    for definition in PROVIDER_REGISTRY:
        provider = definition["platform"]
        if provider == "Other":
            continue
        keys = list(definition["required_environment"])
        present = all(bool(os.getenv(key, "").strip()) for key in keys) if keys else False
        meta_provider = provider in {"Facebook", "Instagram"}
        whatsapp_provider = provider == "WhatsApp"
        oauth_provider_keys = {"X": "x", "LinkedIn": "linkedin", "TikTok": "tiktok", "YouTube": "youtube"}
        social_oauth_key = oauth_provider_keys.get(provider)
        implemented = (
            (provider == "Telegram" and definition["implementation_status"] in {"partial", "implemented"})
            or meta_provider or whatsapp_provider or social_oauth_key is not None
        )
        connected_accounts = 0
        publish_ready_accounts = 0
        if meta_provider:
            connected_accounts = int(db.scalar(select(func.count(SocialAccount.id)).where(
                SocialAccount.organization_id == ctx.organization.id,
                SocialAccount.platform == provider,
                SocialAccount.connection_status == "connected",
                SocialAccount.provider_account_id.is_not(None),
            )) or 0)
            if provider == "Facebook" and connected_accounts:
                scope_rows = db.scalars(
                    select(IntegrationCredential.scopes_json)
                    .join(SocialAccount, SocialAccount.id == IntegrationCredential.social_account_id)
                    .where(
                        IntegrationCredential.organization_id == ctx.organization.id,
                        IntegrationCredential.provider == "Facebook",
                        IntegrationCredential.status == "active",
                        SocialAccount.platform == "Facebook",
                        SocialAccount.connection_status == "connected",
                        SocialAccount.provider_account_id.is_not(None),
                    )
                ).all()
                for scopes_json in scope_rows:
                    try:
                        scopes = json.loads(scopes_json)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        scopes = []
                    if isinstance(scopes, list) and "pages_manage_posts" in scopes:
                        publish_ready_accounts += 1
            config_ready = bool(get_meta_config())
            state = (
                "connected_read_write" if provider == "Facebook" and publish_ready_accounts else
                "connected_read_only" if connected_accounts else
                ("authorization_required" if config_ready else "not_configured")
            )
        elif whatsapp_provider:
            connected_accounts = int(db.scalar(select(func.count(SocialAccount.id)).where(
                SocialAccount.organization_id == ctx.organization.id,
                SocialAccount.platform == "WhatsApp",
                SocialAccount.connection_status == "connected",
                SocialAccount.provider_account_id.is_not(None),
            )) or 0)
            config_ready = bool(get_whatsapp_config())
            webhook_ready = bool(get_whatsapp_webhook_secrets())
            state = (
                "connected" if connected_accounts and webhook_ready and config_ready else
                "connected_webhook_pending" if connected_accounts and config_ready else
                "connected_configuration_missing" if connected_accounts else
                "verification_required" if config_ready else "not_configured"
            )
        elif social_oauth_key:
            connected_accounts = int(db.scalar(select(func.count(SocialAccount.id)).where(
                SocialAccount.organization_id == ctx.organization.id,
                SocialAccount.platform == provider,
                SocialAccount.connection_status == "connected",
                SocialAccount.provider_account_id.is_not(None),
            )) or 0)
            config_ready = bool(get_social_oauth_config(social_oauth_key))
            if connected_accounts:
                scope_rows = db.scalars(
                    select(IntegrationCredential.scopes_json)
                    .join(SocialAccount, SocialAccount.id == IntegrationCredential.social_account_id)
                    .where(
                        IntegrationCredential.organization_id == ctx.organization.id,
                        IntegrationCredential.provider == provider,
                        IntegrationCredential.status == "active",
                        SocialAccount.platform == provider,
                        SocialAccount.connection_status == "connected",
                    )
                ).all()
                write_scope = {"X": "tweet.write", "LinkedIn": "w_member_social"}.get(provider)
                if write_scope:
                    for raw_scopes in scope_rows:
                        try:
                            granted = json.loads(raw_scopes)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            granted = []
                        if isinstance(granted, list) and write_scope in granted:
                            publish_ready_accounts += 1
            state = "connected_read_write" if publish_ready_accounts else (
                "connected" if connected_accounts else "authorization_required" if config_ready else "not_configured"
            )
        elif implemented:
            state = "configured_channel_verification_required" if present else "not_configured"
        else:
            state = "credentials_present_flow_pending" if present else "not_configured"
        providers.append({
            "platform": provider,
            "credentials_present": present,
            "connector_implemented": implemented,
            "implementation_status": definition["implementation_status"],
            "status": state,
            "required_environment": keys,
            "method": definition["method"],
            "docs_url": definition["docs_url"],
            "limitations": definition["limitations_ar"],
            "description": definition["description_ar"],
            "implemented_capabilities": list(definition["implemented_capabilities"]),
            "planned_capabilities": list(definition["planned_capabilities"]),
            "connected_accounts": connected_accounts if (meta_provider or whatsapp_provider or social_oauth_key) else 0,
            "webhook_ready": bool(get_whatsapp_webhook_secrets()) if whatsapp_provider else None,
            "publish_ready_accounts": publish_ready_accounts if (provider == "Facebook" or social_oauth_key) else 0,
            "supported_actions": (
                ["verify_channel", "publish_text"] if provider == "Telegram" else
                (["verify_business_number", "send_text", "receive_webhooks"] if provider == "WhatsApp" and connected_accounts else
                (["account_authorization", "read_page_posts", "read_page_videos"] + (["publish_page_text"] if publish_ready_accounts else [])) if provider == "Facebook" else
                (["account_authorization", "read_profile"] + (["publish_text"] if publish_ready_accounts else [])) if provider in {"X", "LinkedIn"} else
                (["account_authorization", "read_profile"] if provider in {"TikTok", "YouTube"} else
                list(definition["implemented_capabilities"])))
            ) if implemented else [],
        })

    telegram_token_present = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    external_publishing_enabled = env_flag("ENABLE_EXTERNAL_PUBLISHING", default=False)
    verified_telegram_channels = db.scalar(select(func.count(SocialAccount.id)).where(
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == "Telegram",
        SocialAccount.connection_status == "connected",
        SocialAccount.provider_account_id.is_not(None),
    )) or 0
    telegram_destination_ready = telegram_token_present and verified_telegram_channels > 0
    for provider in providers:
        if provider["platform"] == "Telegram":
            provider["verified_destinations"] = int(verified_telegram_channels)
            provider["status"] = (
                "ready" if telegram_destination_ready and external_publishing_enabled else
                "publishing_disabled" if telegram_destination_ready and not external_publishing_enabled else
                "configured_channel_verification_required" if telegram_token_present else "not_configured"
            )
    facebook_destination_ready = any(
        item["platform"] == "Facebook" and int(item.get("publish_ready_accounts", 0)) > 0
        for item in providers
    )
    oauth_text_destination_ready = any(
        item["platform"] in {"X", "LinkedIn"} and int(item.get("publish_ready_accounts", 0)) > 0
        for item in providers
    )
    ready = bool(external_publishing_enabled and (telegram_destination_ready or facebook_destination_ready or oauth_text_destination_ready))
    return {
        "providers": providers,
        "external_actions_enabled": ready,
        "external_publishing_enabled": external_publishing_enabled,
        "external_publishing_disabled_by_default": not external_publishing_enabled,
        "note": (
            "النشر الخارجي متوقف افتراضيًا كإجراء أمان. وظائف إنشاء المحتوى وإدارته محليًا متاحة، ولن يتم إرسال أي منشور إلى منصة خارجية حتى تفعيل ENABLE_EXTERNAL_PUBLISHING صراحةً بعد مراجعة الجاهزية."
            if not external_publishing_enabled else
            "النشر الخارجي مفعّل في إعدادات الخادم؛ يمكن نشر نص إلى صفحات Facebook التي منحت pages_manage_posts فعليًا، أو إلى وجهات Telegram المتحقق منها. بقية وظائف المنصات تحتاج موصلات وموافقات مستقلة."
        ),
    }


@app.post(f"{API_PREFIX}/integrations/telegram/verify")
async def verify_telegram_destination(data: TelegramDestinationVerifyIn, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="موصل Telegram غير مهيأ. أضف TELEGRAM_BOT_TOKEN إلى إعدادات الخادم ثم أعد تشغيله.")
    account = db.scalar(select(SocialAccount).where(SocialAccount.id == data.social_account_id, SocialAccount.organization_id == ctx.organization.id))
    if not account:
        not_found("الحساب الاجتماعي")
    if account.platform != "Telegram":
        raise HTTPException(status_code=422, detail="التحقق متاح لحسابات Telegram فقط")
    target = (account.handle or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="أدخل اسم قناة Telegram مثل @my_channel في خانة المعرّف أولًا")
    connector = get_connector(
        account.platform,
        telegram_verify_fn=telegram_verify_channel,
        telegram_publish_fn=telegram_send_text,
    )
    if connector is None or not connector.capabilities.verify_destination:
        raise HTTPException(status_code=501, detail="لا يوجد موصل تحقق فعّال لهذه المنصة")
    try:
        checked = await connector.verify_destination(token, target)
    except TelegramDeliveryUnknown as exc:
        raise HTTPException(status_code=502, detail="تعذر تأكيد اتصال Telegram بسبب مشكلة شبكة. لم يتم تغيير حالة القناة.") from exc
    except TelegramAPIError as exc:
        raise HTTPException(status_code=502, detail=f"تعذر التحقق من القناة: {str(exc)[:350]}") from exc
    chat = checked["chat"]
    account.provider_account_id = str(chat.get("id"))
    account.connection_status = "connected"
    account.last_synced_at = utcnow()
    if chat.get("username"):
        account.handle = "@" + str(chat["username"]).lstrip("@")
    audit(db, ctx, "telegram.destination_verified", "social_account", account.id,
          {"platform": "Telegram", "chat_type": chat.get("type"), "provider_account_id": account.provider_account_id})
    db.commit(); db.refresh(account)
    return {"verified": True, "account": {"id": account.id, "platform": account.platform, "account_name": account.account_name,
            "handle": account.handle, "connection_status": account.connection_status, "provider_account_id": account.provider_account_id},
            "bot": checked["bot"], "destination": chat}


@app.get(f"{API_PREFIX}/dashboard")
def dashboard(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Return only metrics from areas the current role is allowed to read."""
    oid = ctx.organization.id
    readable = ROLE_READ_PERMISSIONS.get(ctx.membership.role, set())
    # Values remain null when the current role cannot read that area.  The
    # dashboard must never turn hidden metrics into misleading zeroes.
    counts: dict[str, int | None] = {
        "contacts": None,
        "open_leads": None,
        "active_tasks": None,
        "total_tasks": None,
        "completed_tasks": None,
        "overdue_tasks": None,
        "scheduled_posts": None,
        "total_posts": None,
        "draft_posts": None,
        "in_review_posts": None,
        "approved_posts": None,
        "changes_requested_posts": None,
        "published_posts": None,
        "failed_posts": None,
        "cancelled_posts": None,
        "publishing_posts": None,
        "uncertain_posts": None,
        "social_accounts": None,
        "connected_accounts": None,
    }
    pipeline_value: float | None = None
    if "contacts" in readable:
        counts["contacts"] = db.scalar(select(func.count(Contact.id)).where(Contact.organization_id == oid)) or 0
        counts["open_leads"] = db.scalar(select(func.count(Contact.id)).where(Contact.organization_id == oid, Contact.stage.notin_(["won", "lost"]))) or 0
        pipeline_value = float(db.scalar(select(func.coalesce(func.sum(Contact.value), 0.0)).where(Contact.organization_id == oid, Contact.stage.notin_(["won", "lost"]))) or 0.0)
    if "tasks" in readable:
        task_status_counts = dict(db.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.organization_id == oid)
            .group_by(Task.status)
        ).all())
        counts["total_tasks"] = sum(task_status_counts.values())
        counts["active_tasks"] = int(task_status_counts.get("open", 0) + task_status_counts.get("in_progress", 0))
        counts["completed_tasks"] = int(task_status_counts.get("done", 0))
        counts["overdue_tasks"] = db.scalar(select(func.count(Task.id)).where(
            Task.organization_id == oid,
            Task.status.in_(["open", "in_progress"]),
            Task.due_at.is_not(None),
            Task.due_at < utcnow(),
        )) or 0
    if "posts" in readable:
        post_status_counts = dict(db.execute(
            select(Post.status, func.count(Post.id))
            .where(Post.organization_id == oid)
            .group_by(Post.status)
        ).all())
        counts["total_posts"] = sum(post_status_counts.values())
        for status_key, status_value in (
            ("scheduled_posts", "scheduled"),
            ("draft_posts", "draft"),
            ("in_review_posts", "in_review"),
            ("approved_posts", "approved"),
            ("changes_requested_posts", "changes_requested"),
            ("published_posts", "published"),
            ("failed_posts", "failed"),
            ("cancelled_posts", "cancelled"),
            ("publishing_posts", "publishing"),
            ("uncertain_posts", "delivery_unknown"),
        ):
            counts[status_key] = int(post_status_counts.get(status_value, 0))
    if "accounts" in readable:
        counts["social_accounts"] = db.scalar(select(func.count(SocialAccount.id)).where(SocialAccount.organization_id == oid)) or 0
        counts["connected_accounts"] = db.scalar(select(func.count(SocialAccount.id)).where(SocialAccount.organization_id == oid, SocialAccount.connection_status == "connected")) or 0
    return {
        "organization": {"id": ctx.organization.id, "name": ctx.organization.name, "timezone": ctx.organization.timezone},
        "counts": counts,
        "pipeline_value": pipeline_value,
        "visible_areas": sorted(readable),
        "integrations_live": False,
    }

# A scheduled post is stored locally; publishing is a separate explicit action. At present,
# only plain-text Telegram channel publishing is implemented.
@app.get(f"{API_PREFIX}/posts", response_model=list[PostOut])
def list_posts(status: str | None = None, platform: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "posts")
    stmt = select(Post).where(Post.organization_id == ctx.organization.id)
    if status: stmt = stmt.where(Post.status == status)
    if platform: stmt = stmt.where(Post.platform == platform)
    if q:
        pattern = f"%{q[:100]}%"
        stmt = stmt.where(or_(Post.title.ilike(pattern), Post.content.ilike(pattern)))
    rows = list(db.scalars(stmt.order_by(Post.updated_at.desc()).limit(limit).offset(offset)).all())
    notes = latest_post_review_notes(db, ctx.organization.id, [row.id for row in rows])
    payload = []
    for row in rows:
        item = PostOut.model_validate(row).model_dump()
        item["review_note"] = notes.get(row.id) if row.status == "changes_requested" else None
        payload.append(item)
    return payload


def validate_post_destination(data, organization_id: str, db: Session):
    if not data.social_account_id:
        return None
    account = db.scalar(select(SocialAccount).where(SocialAccount.id == data.social_account_id, SocialAccount.organization_id == organization_id))
    if not account:
        raise HTTPException(status_code=422, detail="وجهة النشر غير موجودة في مساحة العمل هذه")
    if account.platform != data.platform:
        raise HTTPException(status_code=422, detail="منصة المنشور لا تطابق منصة الحساب المحدد")
    return account


@app.get(f"{API_PREFIX}/posts/calendar")
def posts_calendar(
    start_date: date = Query(..., description="First organization-local calendar date, inclusive"),
    end_date: date = Query(..., description="Last organization-local calendar date, inclusive"),
    status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    """Bounded content-planning feed, scoped to the current organization and role.

    Calendar dates are interpreted in the organization's configured timezone. Stored
    instants are queried using UTC bounds so that month edges and DST are handled
    without assuming the browser's timezone matches the workspace's timezone.
    """
    require_read(ctx, "posts")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="تاريخ نهاية التقويم يجب ألا يسبق تاريخ البداية")
    if end_date == date.max:
        raise HTTPException(status_code=422, detail="تاريخ نهاية التقويم خارج النطاق المدعوم")
    if (end_date - start_date).days > 62:
        raise HTTPException(status_code=422, detail="نطاق التقويم كبير؛ اختر فترة لا تتجاوز 63 يومًا")

    valid_statuses = {"draft", "in_review", "approved", "changes_requested", "scheduled", "cancelled", "published", "failed", "publishing", "delivery_unknown"}
    valid_platforms = {"Facebook", "Instagram", "WhatsApp", "Telegram", "X", "YouTube", "TikTok", "LinkedIn", "Other"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=422, detail="حالة المنشور غير معروفة")
    if platform and platform not in valid_platforms:
        raise HTTPException(status_code=422, detail="المنصة غير معروفة")

    effective_timezone = ctx.organization.timezone or "Asia/Hebron"
    try:
        org_tz = ZoneInfo(effective_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        effective_timezone = "Asia/Hebron"
        org_tz = ZoneInfo(effective_timezone)
    start_local = datetime.combine(start_date, time.min, tzinfo=org_tz)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=org_tz)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    def apply_filters(stmt):
        if status:
            stmt = stmt.where(Post.status == status)
        if platform:
            stmt = stmt.where(Post.platform == platform)
        query_text = (q or "").strip()[:100]
        if query_text:
            pattern = f"%{query_text}%"
            stmt = stmt.where(or_(Post.title.ilike(pattern), Post.content.ilike(pattern)))
        return stmt

    organization_posts = select(Post).where(Post.organization_id == ctx.organization.id)
    calendar_stmt = organization_posts.where(
        Post.scheduled_at.is_not(None),
        Post.scheduled_at >= start_utc,
        Post.scheduled_at < end_utc,
    )
    calendar_stmt = apply_filters(calendar_stmt).order_by(Post.scheduled_at.asc(), Post.updated_at.desc())
    calendar_count_stmt = apply_filters(select(func.count(Post.id)).where(
        Post.organization_id == ctx.organization.id,
        Post.scheduled_at.is_not(None),
        Post.scheduled_at >= start_utc,
        Post.scheduled_at < end_utc,
    ))
    # The UI needs exact status totals plus a bounded set of events; avoid returning
    # an unbounded list if a workspace has unusually dense content activity.
    total_in_range = int(db.scalar(calendar_count_stmt) or 0)
    items = list(db.scalars(calendar_stmt.limit(500)).all())

    backlog_stmt = organization_posts.where(
        Post.status.in_(["draft", "in_review", "approved", "changes_requested", "scheduled"]),
        Post.scheduled_at.is_(None),
    )
    backlog_stmt = apply_filters(backlog_stmt).order_by(Post.updated_at.desc()).limit(100)
    backlog_count_stmt = select(func.count(Post.id)).where(
        Post.organization_id == ctx.organization.id,
        Post.status.in_(["draft", "in_review", "approved", "changes_requested", "scheduled"]),
        Post.scheduled_at.is_(None),
    )
    backlog_count = int(db.scalar(backlog_count_stmt) or 0)
    backlog = list(db.scalars(backlog_stmt).all())
    review_notes = latest_post_review_notes(db, ctx.organization.id, [row.id for row in [*items, *backlog]])
    def calendar_item_payload(row: Post) -> dict[str, Any]:
        item = PostOut.model_validate(row).model_dump()
        item["review_note"] = review_notes.get(row.id) if row.status == "changes_requested" else None
        return item
    calendar_items = [calendar_item_payload(row) for row in items]
    backlog_items = [calendar_item_payload(row) for row in backlog]

    status_rows = db.execute(
        select(Post.status, func.count(Post.id))
        .where(Post.organization_id == ctx.organization.id)
        .group_by(Post.status)
    ).all()
    counts_by_status = {key: int(value) for key, value in status_rows}
    counts = {
        "total": sum(counts_by_status.values()),
        "draft": counts_by_status.get("draft", 0),
        "scheduled": counts_by_status.get("scheduled", 0),
        "published": counts_by_status.get("published", 0),
        "failed": counts_by_status.get("failed", 0),
        "publishing": counts_by_status.get("publishing", 0),
        "delivery_unknown": counts_by_status.get("delivery_unknown", 0),
        "cancelled": counts_by_status.get("cancelled", 0),
    }
    return {
        "timezone": effective_timezone,
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "items": calendar_items,
        "items_count": total_in_range,
        "truncated": total_in_range > len(items),
        "backlog": backlog_items,
        "backlog_count": backlog_count,
        "counts": counts,
    }


@app.post(f"{API_PREFIX}/posts", response_model=PostOut, status_code=201)
def create_post(data: PostCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    validate_post_destination(data, ctx.organization.id, db)
    obj = Post(**data.model_dump(), organization_id=ctx.organization.id, created_by=ctx.user.id)
    db.add(obj); db.flush(); audit(db, ctx, "created", "post", obj.id, {"title": obj.title}); db.commit(); db.refresh(obj)
    return obj

@app.put(f"{API_PREFIX}/posts/{{post_id}}", response_model=PostOut)
def update_post(post_id: str, data: PostUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    obj = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not obj: not_found("المنشور")
    if obj.status in {"publishing", "published", "delivery_unknown", "in_review", "approved"}:
        raise HTTPException(status_code=409, detail="لا يمكن تعديل منشور قيد الإرسال أو النشر أو المراجعة أو معتمد؛ أعده للمراجعة أو انتظر قرار المراجع")
    validate_post_destination(data, ctx.organization.id, db)
    for key, value in data.model_dump().items(): setattr(obj, key, value)
    obj.publish_error = None
    audit(db, ctx, "updated", "post", obj.id, {"title": obj.title}); db.commit(); db.refresh(obj)
    return obj

@app.post(f"{API_PREFIX}/posts/{{post_id}}/submit-review", response_model=PostOut)
def submit_post_for_review(post_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Send a draft into the review queue. Approval never happens through a generic update."""
    require_write(ctx, "posts")
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not post:
        not_found("المنشور")
    if post.status not in {"draft", "changes_requested", "scheduled"}:
        raise HTTPException(status_code=409, detail="يمكن إرسال المسودة أو الموعد المحفوظ للمراجعة فقط")
    previous_status = post.status
    post.status = "in_review"
    post.updated_at = utcnow()
    audit(db, ctx, "post.review_requested", "post", post.id, {"previous_status": previous_status})
    db.commit(); db.refresh(post)
    return post


@app.post(f"{API_PREFIX}/posts/{{post_id}}/approve", response_model=PostOut)
def approve_post(post_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Only workspace owners/admins can approve content submitted for review."""
    require_roles(ctx, {"owner", "admin"})
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not post:
        not_found("المنشور")
    if post.status != "in_review":
        raise HTTPException(status_code=409, detail="لا يمكن اعتماد منشور لم يُرسل إلى قائمة المراجعة")
    post.status = "approved"
    post.updated_at = utcnow()
    audit(db, ctx, "post.approved", "post", post.id, {"title": post.title})
    db.commit(); db.refresh(post)
    return post


@app.post(f"{API_PREFIX}/posts/{{post_id}}/request-changes", response_model=PostOut)
def request_post_changes(post_id: str, data: PostReviewNoteIn, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Return reviewed content to the author with an auditable reviewer note."""
    require_roles(ctx, {"owner", "admin"})
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not post:
        not_found("المنشور")
    if post.status != "in_review":
        raise HTTPException(status_code=409, detail="طلب التعديل متاح فقط للمحتوى قيد المراجعة")
    post.status = "changes_requested"
    post.updated_at = utcnow()
    audit(db, ctx, "post.changes_requested", "post", post.id, {"note": data.note})
    db.commit(); db.refresh(post)
    return post


@app.delete(f"{API_PREFIX}/posts/{{post_id}}", status_code=204)
def delete_post(post_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    obj = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not obj: not_found("المنشور")
    if obj.status in {"publishing", "published", "delivery_unknown", "in_review", "approved"}:
        raise HTTPException(status_code=409, detail="لا يمكن حذف منشور قيد النشر أو المراجعة أو معتمد؛ احتفظ بسجل القرار")
    audit(db, ctx, "deleted", "post", obj.id); db.delete(obj); db.commit(); return Response(status_code=204)


@app.post(f"{API_PREFIX}/posts/{{post_id}}/publish", response_model=PostOut)
async def publish_post(post_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    if not env_flag("ENABLE_EXTERNAL_PUBLISHING", default=False):
        raise HTTPException(status_code=423, detail="النشر الخارجي متوقف افتراضيًا. لم يتم إرسال أي محتوى؛ راجع إعدادات الخادم قبل تفعيله.")
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not post:
        not_found("المنشور")
    supported_platforms = {"Telegram", "Facebook", "X", "LinkedIn"}
    if post.platform not in supported_platforms:
        raise HTTPException(status_code=501, detail="النشر الخارجي النصي متاح حاليًا لصفحات Facebook وX وLinkedIn وقنوات Telegram فقط")
    if post.status in {"published", "publishing", "delivery_unknown"}:
        raise HTTPException(status_code=409, detail="حالة المنشور لا تسمح بإعادة الإرسال؛ تحقق من الوجهة قبل أي محاولة جديدة")
    if post.status not in {"draft", "scheduled", "approved", "failed"}:
        raise HTTPException(status_code=409, detail="لا يمكن نشر هذا المنشور من حالته الحالية")
    if not post.social_account_id:
        raise HTTPException(status_code=422, detail="اختر حسابًا اجتماعيًا للمنشور أولًا")
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == post.social_account_id,
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == post.platform,
    ))
    if not account or account.connection_status != "connected" or not account.provider_account_id:
        raise HTTPException(status_code=409, detail="تحقق من الحساب الاجتماعي أولًا من شاشة الحسابات")

    telegram_token = ""
    meta_config = None
    credential = None
    required_scope = {"Facebook": "pages_manage_posts", "X": "tweet.write", "LinkedIn": "w_member_social"}.get(post.platform)
    if post.platform == "Telegram":
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not telegram_token:
            raise HTTPException(status_code=503, detail="موصل Telegram غير مهيأ على الخادم")
    else:
        if post.platform == "Facebook":
            meta_config = get_meta_config()
            if not meta_config:
                raise HTTPException(status_code=503, detail="إعداد Meta غير مكتمل على الخادم")
        try:
            credential = load_provider_credential(
                db, organization_id=ctx.organization.id, social_account_id=account.id,
            )
        except (CredentialStoreError, CredentialScopeError, TokenVaultError) as exc:
            raise HTTPException(status_code=409, detail="تعذر فتح بيانات اعتماد الحساب بأمان؛ أعد ربط المنصة.") from exc
        if credential is None:
            raise HTTPException(status_code=409, detail="لا توجد بيانات اعتماد مشفرة لهذا الحساب؛ أعد ربط المنصة.")
        if required_scope and required_scope not in credential.scopes:
            raise HTTPException(status_code=409, detail=f"لم يمنح الحساب صلاحية {required_scope}. أعد التفويض مع الموافقة على الصلاحية المطلوبة.")

    text_body = (post.content or "").strip() or post.title.strip()
    if not text_body:
        raise HTTPException(status_code=422, detail="أضف نصًا للمنشور قبل النشر")
    max_chars = 4096 if post.platform == "Telegram" else 280 if post.platform == "X" else 3000 if post.platform == "LinkedIn" else 60000
    if len(text_body) > max_chars:
        raise HTTPException(status_code=422, detail=f"يتجاوز النص الحد المسموح لهذه المنصة وهو {max_chars} حرفًا")

    result = db.execute(update(Post).where(
        Post.id == post.id, Post.organization_id == ctx.organization.id,
        Post.status.in_(["draft", "scheduled", "approved", "failed"]),
    ).values(status="publishing", publish_error=None, updated_at=utcnow()))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="بدأت محاولة نشر أخرى لهذا المنشور؛ حدّث الصفحة وتحقق من حالته")
    db.commit()
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))

    try:
        if post.platform == "Telegram":
            connector = get_connector(account.platform, telegram_verify_fn=telegram_verify_channel, telegram_publish_fn=telegram_send_text)
            if connector is None or not connector.capabilities.publish_text:
                raise TelegramAPIError("لا يوجد موصل نشر نصي فعّال لقناة Telegram.")
            delivery = await connector.publish_text(telegram_token, account.provider_account_id, text_body)
        elif post.platform == "Facebook":
            delivery = await meta_publish_page_text(meta_config, account.provider_account_id, credential.access_token, text_body)
        else:
            delivery = await publish_social_text(post.platform.casefold(), credential.access_token, account.provider_account_id, text_body)
    except (TelegramDeliveryUnknown, MetaDeliveryUnknown, SocialDeliveryUnknown) as exc:
        post.status = "delivery_unknown"
        post.publish_error = "تعذر تأكيد نتيجة الطلب. افحص الحساب الخارجي قبل أي إعادة محاولة."
        post.updated_at = utcnow()
        audit(db, ctx, f"{post.platform.lower()}.publish_outcome_unknown", "post", post.id, {"account_id": account.id})
        db.commit()
        raise HTTPException(status_code=502, detail=post.publish_error) from exc
    except (TelegramAPIError, MetaGraphError, SocialOAuthError) as exc:
        post.status = "failed"
        post.publish_error = str(exc)[:1000]
        post.updated_at = utcnow()
        audit(db, ctx, f"{post.platform.lower()}.publish_failed", "post", post.id, {"account_id": account.id})
        db.commit()
        raise HTTPException(status_code=502, detail=f"رفضت المنصة نشر الرسالة: {str(exc)[:300]}") from exc

    post.status = "published"
    post.published_at = utcnow()
    provider_post_id = delivery.get("message_id") or delivery.get("id") or delivery.get("post_id")
    post.provider_post_id = str(provider_post_id) if provider_post_id is not None else None
    post.publish_error = None
    post.updated_at = utcnow()
    account.last_synced_at = utcnow()
    audit(db, ctx, f"{post.platform.lower()}.published", "post", post.id, {"account_id": account.id, "provider_post_id": post.provider_post_id})
    db.commit()
    db.refresh(post)
    return post


@app.post(f"{API_PREFIX}/posts/{{post_id}}/resolve-delivery", response_model=PostOut)
def resolve_telegram_delivery(post_id: str, data: TelegramDeliveryResolveIn, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    """Manually reconcile an ambiguous Telegram send after an administrator checks the destination."""
    require_roles(ctx, {"owner", "admin"})
    post = db.scalar(select(Post).where(Post.id == post_id, Post.organization_id == ctx.organization.id))
    if not post: not_found("المنشور")
    if post.platform != "Telegram" or post.status != "delivery_unknown":
        raise HTTPException(status_code=409, detail="يمكن تسوية النتيجة يدويًا فقط لمنشور Telegram ذي نتيجة غير مؤكدة")
    if data.resolution == "published":
        post.status = "published"
        post.published_at = post.published_at or utcnow()
        post.provider_post_id = data.provider_post_id or post.provider_post_id
        post.publish_error = None
        audit_action = "telegram.delivery_resolved_published"
    else:
        post.status = "failed"
        post.publish_error = f"تم التحقق يدويًا من عدم ظهور الرسالة في القناة. ملاحظة: {data.note}"[:1000]
        audit_action = "telegram.delivery_resolved_not_delivered"
    post.updated_at = utcnow()
    audit(db, ctx, audit_action, "post", post.id, {"note": data.note, "provider_post_id": data.provider_post_id})
    db.commit(); db.refresh(post)
    return post

@app.get(f"{API_PREFIX}/contacts", response_model=list[ContactOut])
def list_contacts(q: str | None = None, stage: str | None = None, limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "contacts")
    stmt = select(Contact).where(Contact.organization_id == ctx.organization.id)
    if stage: stmt = stmt.where(Contact.stage == stage)
    if q:
        term = f"%{q[:100]}%"
        stmt = stmt.where((Contact.name.ilike(term)) | (Contact.company.ilike(term)) | (Contact.email.ilike(term)))
    return list(db.scalars(stmt.order_by(Contact.updated_at.desc()).limit(limit).offset(offset)).all())

@app.post(f"{API_PREFIX}/contacts", response_model=ContactOut, status_code=201)
def create_contact(data: ContactCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "contacts")
    payload = data.model_dump(); payload["email"] = str(payload["email"]).lower() if payload["email"] else None
    obj = Contact(**payload, organization_id=ctx.organization.id)
    db.add(obj); db.flush(); audit(db, ctx, "created", "contact", obj.id, {"name": obj.name}); db.commit(); db.refresh(obj)
    return obj

@app.put(f"{API_PREFIX}/contacts/{{contact_id}}", response_model=ContactOut)
def update_contact(contact_id: str, data: ContactUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "contacts")
    obj = db.scalar(select(Contact).where(Contact.id == contact_id, Contact.organization_id == ctx.organization.id))
    if not obj: not_found("العميل")
    payload = data.model_dump(); payload["email"] = str(payload["email"]).lower() if payload["email"] else None
    for key, value in payload.items(): setattr(obj, key, value)
    audit(db, ctx, "updated", "contact", obj.id, {"stage": obj.stage}); db.commit(); db.refresh(obj)
    return obj

@app.delete(f"{API_PREFIX}/contacts/{{contact_id}}", status_code=204)
def delete_contact(contact_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "contacts")
    obj = db.scalar(select(Contact).where(Contact.id == contact_id, Contact.organization_id == ctx.organization.id))
    if not obj: not_found("العميل")
    audit(db, ctx, "deleted", "contact", obj.id); db.delete(obj); db.commit(); return Response(status_code=204)

@app.get(f"{API_PREFIX}/tasks", response_model=list[TaskOut])
def list_tasks(status: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "tasks")
    stmt = select(Task).where(Task.organization_id == ctx.organization.id)
    if status: stmt = stmt.where(Task.status == status)
    if q: stmt = stmt.where(Task.title.ilike(f"%{q[:100]}%"))
    return list(db.scalars(stmt.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc()).limit(limit).offset(offset)).all())

@app.post(f"{API_PREFIX}/tasks", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "tasks")
    obj = Task(**data.model_dump(), organization_id=ctx.organization.id, created_by=ctx.user.id)
    db.add(obj); db.flush(); audit(db, ctx, "created", "task", obj.id, {"title": obj.title}); db.commit(); db.refresh(obj)
    return obj

@app.put(f"{API_PREFIX}/tasks/{{task_id}}", response_model=TaskOut)
def update_task(task_id: str, data: TaskUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "tasks")
    obj = db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == ctx.organization.id))
    if not obj: not_found("المهمة")
    for key, value in data.model_dump().items(): setattr(obj, key, value)
    audit(db, ctx, "updated", "task", obj.id, {"status": obj.status}); db.commit(); db.refresh(obj)
    return obj

@app.delete(f"{API_PREFIX}/tasks/{{task_id}}", status_code=204)
def delete_task(task_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "tasks")
    obj = db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == ctx.organization.id))
    if not obj: not_found("المهمة")
    audit(db, ctx, "deleted", "task", obj.id); db.delete(obj); db.commit(); return Response(status_code=204)



def _social_oauth_cookie_name(provider: str, state: str) -> str:
    digest = hashlib.sha256(f"{provider}:{state}".encode("utf-8")).hexdigest()[:24]
    return f"m_oauth_{provider}_bind_{digest}"


def _social_oauth_redirect(result: str, provider: str) -> RedirectResponse:
    allowed = {"connected", "access_denied", "invalid_state", "not_configured", "connection_failed"}
    code = result if result in allowed else "connection_failed"
    response = RedirectResponse(url=f"/?provider_result={code}&provider={provider}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _upsert_oauth_social_account(db: Session, ctx: AuthContext, identity) -> SocialAccount:
    platform = {"x": "X", "linkedin": "LinkedIn", "tiktok": "TikTok", "youtube": "YouTube"}[identity.provider]
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == platform,
        SocialAccount.provider_account_id == identity.external_id,
    ))
    handle = (identity.handle or f"{identity.provider}:{identity.external_id}")[:180]
    collision = db.scalar(select(SocialAccount).where(
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == platform, SocialAccount.handle == handle,
    ))
    if collision is not None and (account is None or collision.id != account.id):
        handle = f"{identity.provider}:{identity.external_id}"[:180]
        collision = db.scalar(select(SocialAccount).where(
            SocialAccount.organization_id == ctx.organization.id,
            SocialAccount.platform == platform, SocialAccount.handle == handle,
        ))
        if collision is not None and (account is None or collision.id != account.id):
            handle = None
    if account is None:
        account = SocialAccount(
            organization_id=ctx.organization.id, platform=platform,
            account_name=identity.account_name[:160], handle=handle,
            connection_status="connected", provider_account_id=identity.external_id,
            last_synced_at=utcnow(),
        )
        db.add(account)
    else:
        account.account_name = identity.account_name[:160]
        account.handle = handle
        account.connection_status = "connected"
        account.provider_account_id = identity.external_id
        account.last_synced_at = utcnow()
    db.flush()
    store_provider_credential(
        db, organization_id=ctx.organization.id, social_account_id=account.id,
        actor_user_id=ctx.user.id, provider=platform, access_token=identity.access_token,
        refresh_token=identity.refresh_token, token_type=identity.token_type,
        scopes=identity.scopes, expires_at=identity.expires_at,
    )
    return account


@app.post(f"{API_PREFIX}/integrations/oauth/{{provider}}/connect-url")
def social_oauth_connect_url(
    provider: str, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db),
):
    require_roles(ctx, {"owner", "admin"})
    provider = (provider or "").casefold()
    if provider not in {"x", "linkedin", "tiktok", "youtube"}:
        raise HTTPException(status_code=404, detail="موصل OAuth غير معروف.")
    config = get_social_oauth_config(provider)
    if config is None:
        raise HTTPException(status_code=503, detail=f"إعداد OAuth الخاص بـ {provider} غير مكتمل في إعدادات M على الخادم.")
    cleanup_expired_authorization_transactions(db)
    try:
        challenge = create_authorization_transaction(
            db, provider=provider, purpose="connect", user_id=ctx.user.id,
            organization_id=ctx.organization.id, auth_version=int(ctx.user.auth_version or 0),
            ttl_seconds=600,
        )
        db.commit()
    except AuthorizationTransactionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail="لا يمكن بدء ربط هذه المنصة لهذا المستخدم أو مساحة العمل.") from exc
    response = JSONResponse({
        "provider": provider,
        "authorization_url": make_social_authorization_url(config, challenge.state, challenge.code_challenge),
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        key=_social_oauth_cookie_name(provider, challenge.state), value=challenge.browser_binding,
        max_age=600, path=f"{API_PREFIX}/integrations/oauth/{provider}/callback",
        secure=_google_cookie_secure(request), httponly=True, samesite="lax",
    )
    return response


@app.get(f"{API_PREFIX}/integrations/oauth/{{provider}}/callback")
async def social_oauth_callback(
    provider: str, request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, scopes: str | None = None, scope: str | None = None,
    db: Session = Depends(get_db),
):
    provider = (provider or "").casefold()
    if provider not in {"x", "linkedin", "tiktok", "youtube"}:
        return _social_oauth_redirect("not_configured", "unknown")
    if not state or len(state) > 256:
        return _social_oauth_redirect("invalid_state", provider)
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    stored = db.get(OAuthTransaction, state_hash)
    cookie_name = _social_oauth_cookie_name(provider, state)
    secure_cookie = _google_cookie_secure(request)
    if not stored or stored.provider != provider or stored.purpose != "connect":
        return _social_oauth_redirect("invalid_state", provider)
    try:
        consumed = consume_authorization_transaction(
            db, provider=provider, purpose="connect", state=state,
            browser_binding=request.cookies.get(cookie_name, ""),
        )
        db.commit()
    except AuthorizationTransactionError as exc:
        if exc.cleanup_performed:
            db.commit()
        else:
            db.rollback()
        return _social_oauth_redirect("invalid_state", provider)

    def finish(result: str) -> RedirectResponse:
        response = _social_oauth_redirect(result, provider)
        response.delete_cookie(
            key=cookie_name, path=f"{API_PREFIX}/integrations/oauth/{provider}/callback",
            secure=secure_cookie, httponly=True, samesite="lax",
        )
        return response

    if error:
        return finish("access_denied")
    if not code or len(code) > 4096:
        return finish("invalid_state")
    config = get_social_oauth_config(provider)
    actor = db.get(User, consumed.user_id) if consumed.user_id else None
    organization = db.get(Organization, consumed.organization_id) if consumed.organization_id else None
    membership = db.scalar(select(Membership).where(
        Membership.user_id == consumed.user_id, Membership.organization_id == consumed.organization_id,
    )) if consumed.user_id and consumed.organization_id else None
    if config is None or not os.getenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip():
        return finish("not_configured")
    if not actor or not actor.is_active or not organization or membership is None or membership.role not in {"owner", "admin"}:
        return finish("invalid_state")
    ctx = AuthContext(actor, membership, organization)
    try:
        identity = await exchange_and_identify(
            config, code=code, code_verifier=consumed.code_verifier, scope_hint=scopes or scope or "",
        )
        _upsert_oauth_social_account(db, ctx, identity)
        audit(db, ctx, f"integration.{provider}_connected", "provider", None, {
            "account_id": identity.external_id, "scope_count": len(identity.scopes),
        })
        db.commit()
        return finish("connected")
    except (SocialOAuthError, CredentialStoreError, CredentialScopeError, TokenVaultError, IntegrityError):
        db.rollback()
        security_logger.warning("social_oauth_connection_failed provider=%s organization_id=%s", provider, organization.id)
        return finish("connection_failed")
    except Exception:
        db.rollback()
        security_logger.exception("social_oauth_connection_unexpected_failure provider=%s organization_id=%s", provider, organization.id)
        return finish("connection_failed")


@app.get(f"{API_PREFIX}/integrations/oauth/{{provider}}/accounts/{{account_id}}/media")
async def social_oauth_account_media(
    provider: str, account_id: str, limit: int = Query(30, ge=1, le=50),
    ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db),
):
    require_read(ctx, "accounts")
    provider = (provider or "").casefold()
    platforms = {"x": "X", "tiktok": "TikTok", "youtube": "YouTube"}
    if provider not in platforms:
        raise HTTPException(status_code=404, detail="قراءة المحتوى غير متاحة لهذا المزوّد حاليًا.")
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == account_id,
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == platforms[provider],
        SocialAccount.connection_status == "connected",
        SocialAccount.provider_account_id.is_not(None),
    ))
    if account is None:
        raise HTTPException(status_code=404, detail="الحساب غير متصل أو غير موجود ضمن مساحة العمل الحالية.")
    try:
        credential = load_provider_credential(
            db, organization_id=ctx.organization.id, social_account_id=account.id,
        )
        if credential is None:
            raise HTTPException(status_code=409, detail="لا توجد بيانات اعتماد لهذا الحساب؛ أعد ربط المنصة.")
        items = await fetch_social_recent_content(
            provider, credential.access_token, account.provider_account_id,
            scopes=credential.scopes, limit=limit,
        )
    except HTTPException:
        raise
    except (SocialOAuthError, CredentialStoreError, CredentialScopeError, TokenVaultError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc
    account.last_synced_at = utcnow()
    audit(db, ctx, f"integration.{provider}_media_read", "social_account", account.id, {"count": len(items)})
    db.commit()
    return {
        "account": {"id": account.id, "platform": account.platform, "account_name": account.account_name, "handle": account.handle},
        "source": f"{provider}_official_api", "items": items, "fetched_at": utcnow(),
    }


def _meta_binding_cookie_name(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()[:24]
    return f"m_oauth_meta_bind_{digest}"


def _meta_result_redirect(result: str, connected_count: int | None = None) -> RedirectResponse:
    allowed = {"connected", "access_denied", "invalid_state", "not_configured", "no_pages", "connection_failed", "setup_required"}
    code = result if result in allowed else "connection_failed"
    suffix = f"&count={int(connected_count)}" if connected_count is not None else ""
    response = RedirectResponse(url=f"/?meta_result={code}{suffix}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _upsert_meta_social_account(
    db: Session, ctx: AuthContext, *, platform: str, external_id: str, account_name: str,
    handle: str, access_token: str, scopes: tuple[str, ...],
) -> SocialAccount:
    """Store verified provider identities separately from encrypted token material."""
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == platform,
        SocialAccount.provider_account_id == external_id,
    ))
    clean_handle = (handle or f"meta:{external_id}")[:180]
    collision = db.scalar(select(SocialAccount).where(
        SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform == platform, SocialAccount.handle == clean_handle,
    ))
    if collision is not None and (account is None or collision.id != account.id):
        clean_handle = f"meta:{external_id}"[:180]
        collision = db.scalar(select(SocialAccount).where(
            SocialAccount.organization_id == ctx.organization.id,
            SocialAccount.platform == platform, SocialAccount.handle == clean_handle,
        ))
        if collision is not None and (account is None or collision.id != account.id):
            clean_handle = None
    if account is None:
        account = SocialAccount(
            organization_id=ctx.organization.id, platform=platform, account_name=account_name[:160],
            handle=clean_handle, connection_status="connected", provider_account_id=external_id,
            last_synced_at=utcnow(),
        )
        db.add(account)
    else:
        account.account_name = account_name[:160]
        account.handle = clean_handle
        account.connection_status = "connected"
        account.provider_account_id = external_id
        account.last_synced_at = utcnow()
    db.flush()
    store_provider_credential(
        db, organization_id=ctx.organization.id, social_account_id=account.id,
        actor_user_id=ctx.user.id, provider=platform, access_token=access_token,
        scopes=scopes, expires_at=None,
    )
    return account



@app.post(f"{API_PREFIX}/integrations/whatsapp/verify")
async def verify_whatsapp_business_number(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    config = get_whatsapp_config()
    if config is None:
        raise HTTPException(status_code=503, detail="أضف WHATSAPP_PHONE_NUMBER_ID وWHATSAPP_ACCESS_TOKEN إلى إعدادات الخادم ثم أعد تشغيل M.")
    if not os.getenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip():
        raise HTTPException(status_code=503, detail="خزنة رموز المنصات غير مهيأة؛ أعد تشغيل M لتوليد مفتاح التشفير.")
    try:
        remote = await whatsapp_verify_business_number(config)
    except WhatsAppCloudError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:350]) from exc
    phone_id = str(remote["id"])
    foreign = db.scalar(select(SocialAccount).where(
        SocialAccount.platform == "WhatsApp",
        SocialAccount.provider_account_id == phone_id,
        SocialAccount.organization_id != ctx.organization.id,
        SocialAccount.connection_status == "connected",
    ))
    if foreign is not None:
        raise HTTPException(status_code=409, detail="رقم WhatsApp Business هذا مرتبط بمساحة عمل أخرى داخل هذا الخادم.")
    display_number = str(remote.get("display_phone_number") or "").strip()
    verified_name = str(remote.get("verified_name") or "").strip()
    account = _upsert_meta_social_account(
        db, ctx, platform="WhatsApp", external_id=phone_id,
        account_name=(verified_name or display_number or "WhatsApp Business"),
        handle=(display_number or f"wa:{phone_id}"),
        access_token=config["access_token"], scopes=(),
    )
    account.last_synced_at = utcnow()
    audit(db, ctx, "integration.whatsapp_business_verified", "social_account", account.id, {
        "phone_number_id": phone_id, "has_display_number": bool(display_number),
        "has_verified_name": bool(verified_name),
    })
    db.commit()
    db.refresh(account)
    return {
        "verified": True,
        "account": {
            "id": account.id, "platform": account.platform, "account_name": account.account_name,
            "handle": account.handle, "connection_status": account.connection_status,
            "provider_account_id": account.provider_account_id,
        },
        "business": remote,
        "webhook_ready": bool(get_whatsapp_webhook_secrets()),
    }


@app.get(f"{API_PREFIX}/webhooks/whatsapp")
def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    webhook_secrets = get_whatsapp_webhook_secrets()
    if not webhook_secrets:
        raise HTTPException(status_code=503, detail="WhatsApp webhook secrets are not configured.")
    expected_token, _ = webhook_secrets
    if mode != "subscribe" or not verify_token or not secrets.compare_digest(verify_token, expected_token) or challenge is None:
        raise HTTPException(status_code=403, detail="WhatsApp webhook verification was rejected.")
    return Response(content=challenge, media_type="text/plain")


@app.post(f"{API_PREFIX}/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    webhook_secrets = get_whatsapp_webhook_secrets()
    if not webhook_secrets:
        raise HTTPException(status_code=503, detail="WhatsApp webhook secrets are not configured.")
    _, app_secret = webhook_secrets
    size = request.headers.get("content-length", "")
    if size.isdigit() and int(size) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds the allowed size.")
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, request.headers.get("x-hub-signature-256", ""), app_secret):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature.")
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Webhook JSON is invalid.")
    if not isinstance(event, dict) or event.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=400, detail="Unexpected webhook event object.")

    stored_messages = 0
    entries = event.get("entry") if isinstance(event.get("entry"), list) else []
    for entry in entries:
        changes = entry.get("changes", []) if isinstance(entry, dict) else []
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone_id = str(metadata.get("phone_number_id") or "")
            account = db.scalar(select(SocialAccount).where(
                SocialAccount.platform == "WhatsApp",
                SocialAccount.provider_account_id == phone_id,
                SocialAccount.connection_status == "connected",
            ))
            if account is None:
                continue
            org_id = account.organization_id
            names_by_phone = {}
            for profile in value.get("contacts", []) if isinstance(value.get("contacts"), list) else []:
                if isinstance(profile, dict):
                    wa_id = str(profile.get("wa_id") or "")
                    name = profile.get("profile", {}).get("name", "") if isinstance(profile.get("profile"), dict) else ""
                    if wa_id:
                        names_by_phone[wa_id] = str(name or "").strip()
            for incoming in value.get("messages", []) if isinstance(value.get("messages"), list) else []:
                if not isinstance(incoming, dict):
                    continue
                message_id = str(incoming.get("id") or "")
                sender = str(incoming.get("from") or "")
                if not message_id or not re.fullmatch(r"[0-9]{7,20}", sender):
                    continue
                duplicate = db.scalar(select(Message.id).where(
                    Message.organization_id == org_id, Message.provider_message_id == message_id,
                ))
                if duplicate:
                    continue
                kind = str(incoming.get("type") or "unknown")
                segment = incoming.get(kind) if isinstance(incoming.get(kind), dict) else {}
                if kind == "text":
                    body_text = str(segment.get("body") or "").strip()
                elif kind in {"image", "video", "document", "audio", "sticker"}:
                    caption = str(segment.get("caption") or "").strip()
                    media_name = {"image":"صورة", "video":"فيديو", "document":"مستند", "audio":"رسالة صوتية", "sticker":"ملصق"}.get(kind, "وسيط")
                    media_id = str(segment.get("id") or "")
                    body_text = f"[{media_name} وارد عبر WhatsApp]" + (f" {caption}" if caption else "") + (f" (media_id: {media_id})" if media_id else "")
                elif kind == "interactive":
                    button = segment.get("button_reply") if isinstance(segment.get("button_reply"), dict) else {}
                    list_reply = segment.get("list_reply") if isinstance(segment.get("list_reply"), dict) else {}
                    body_text = str(button.get("title") or list_reply.get("title") or "رد تفاعلي عبر WhatsApp")
                else:
                    body_text = f"[رسالة WhatsApp من النوع {kind}]"
                if not body_text:
                    continue
                phone = "+" + sender
                contact = db.scalar(select(Contact).where(
                    Contact.organization_id == org_id, or_(Contact.phone == phone, Contact.phone == sender),
                ))
                if contact is None:
                    contact = Contact(
                        organization_id=org_id, name=names_by_phone.get(sender) or phone,
                        phone=phone, source="WhatsApp", stage="new", value=0, notes="",
                    )
                    db.add(contact)
                    db.flush()
                conversation = db.scalar(select(Conversation).where(
                    Conversation.organization_id == org_id,
                    Conversation.channel == "WhatsApp", Conversation.external_id == sender,
                ))
                if conversation is None:
                    conversation = Conversation(
                        organization_id=org_id, channel="WhatsApp", contact_id=contact.id,
                        external_id=sender, status="open",
                    )
                    db.add(conversation)
                    db.flush()
                now = utcnow()
                db.add(Message(
                    organization_id=org_id, conversation_id=conversation.id,
                    direction="inbound", body=body_text[:20000],
                    provider_message_id=message_id, delivery_status="received", created_at=now,
                ))
                conversation.last_message_at = now
                if conversation.status == "closed":
                    conversation.status = "open"
                stored_messages += 1
            for receipt in value.get("statuses", []) if isinstance(value.get("statuses"), list) else []:
                if not isinstance(receipt, dict) or not receipt.get("id") or not receipt.get("status"):
                    continue
                message = db.scalar(select(Message).where(
                    Message.organization_id == org_id, Message.provider_message_id == str(receipt["id"]),
                ))
                new_status = str(receipt["status"]).casefold()
                if message is not None and new_status in {"sent", "delivered", "read", "failed"}:
                    message.delivery_status = new_status
    db.commit()
    return {"received": True, "stored_messages": stored_messages}


@app.get(f"{API_PREFIX}/integrations/meta/config")
def meta_integration_config():
    config = get_meta_config()
    return {
        "enabled": bool(config), "provider": "Meta",
        "api_version": config["version"] if config else os.getenv("META_GRAPH_API_VERSION", "v26.0"),
        "token_vault_ready": bool(os.getenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip()),
        "supports": ["Facebook Pages", "Instagram Professional accounts linked to a Facebook Page"],
        "note": "يتطلب تطبيق Meta وموافقة OAuth والصلاحيات المناسبة. لا يدعم حسابات Instagram الشخصية غير الاحترافية.",
    }


@app.post(f"{API_PREFIX}/integrations/meta/connect-url")
def meta_connect_url(request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    config = get_meta_config()
    if not config:
        raise HTTPException(status_code=503, detail="أكمل META_APP_ID وMETA_APP_SECRET وMETA_REDIRECT_URI في إعدادات M أولًا.")
    if not os.getenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip():
        raise HTTPException(status_code=503, detail="خزنة رموز المنصات غير مهيأة. أعد تشغيل M لتوليد مفتاحها المحلي أو اضبط PROVIDER_TOKEN_ENCRYPTION_KEY.")
    cleanup_expired_authorization_transactions(db)
    try:
        challenge = create_authorization_transaction(
            db, provider="meta", purpose="connect", user_id=ctx.user.id,
            organization_id=ctx.organization.id, auth_version=int(ctx.user.auth_version or 0),
            ttl_seconds=600,
        )
        db.commit()
    except AuthorizationTransactionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail="لا يمكن بدء ربط Meta لهذا المستخدم أو مساحة العمل.") from exc
    response = JSONResponse({"authorization_url": make_meta_authorization_url(config, challenge.state)})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        key=_meta_binding_cookie_name(challenge.state), value=challenge.browser_binding, max_age=600,
        path=f"{API_PREFIX}/integrations/meta/callback",
        secure=_google_cookie_secure(request), httponly=True, samesite="lax",
    )
    return response


@app.get(f"{API_PREFIX}/integrations/meta/callback")
async def meta_connect_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: Session = Depends(get_db),
):
    if not state or len(state) > 256:
        return _meta_result_redirect("invalid_state")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    stored = db.get(OAuthTransaction, state_hash)
    cookie_name = _meta_binding_cookie_name(state)
    secure_cookie = _google_cookie_secure(request)
    if not stored or stored.provider != "meta" or stored.purpose != "connect":
        return _meta_result_redirect("invalid_state")
    try:
        consumed = consume_authorization_transaction(
            db, provider="meta", purpose="connect", state=state,
            browser_binding=request.cookies.get(cookie_name, ""),
        )
        db.commit()
    except AuthorizationTransactionError as exc:
        if exc.cleanup_performed:
            db.commit()
        else:
            db.rollback()
        return _meta_result_redirect("invalid_state")

    def finish(result: str, count: int | None = None) -> RedirectResponse:
        response = _meta_result_redirect(result, count)
        response.delete_cookie(
            key=cookie_name, path=f"{API_PREFIX}/integrations/meta/callback",
            secure=secure_cookie, httponly=True, samesite="lax",
        )
        return response

    if error:
        return finish("access_denied")
    if not code or len(code) > 4096:
        return finish("invalid_state")
    config = get_meta_config()
    if not config or not os.getenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip():
        return finish("not_configured")
    actor = db.get(User, consumed.user_id) if consumed.user_id else None
    organization = db.get(Organization, consumed.organization_id) if consumed.organization_id else None
    membership = db.scalar(select(Membership).where(
        Membership.user_id == consumed.user_id, Membership.organization_id == consumed.organization_id,
    )) if consumed.user_id and consumed.organization_id else None
    if not actor or not actor.is_active or not organization or membership is None or membership.role not in {"owner", "admin"}:
        return finish("setup_required")
    ctx = AuthContext(actor, membership, organization)
    try:
        token_payload = await exchange_meta_code(config, code)
        long_payload = await exchange_for_long_lived_token(config, token_payload["access_token"])
        granted_scopes = await list_granted_permissions(config, long_payload["access_token"])
        pages = await list_managed_pages(config, long_payload["access_token"])
        if not pages:
            return finish("no_pages")
        scopes = tuple(granted_scopes)
        saved = 0
        for page in pages:
            page_id = str(page.get("id") or "").strip()
            page_token = page.get("access_token")
            if not page_id or not isinstance(page_token, str) or not page_token:
                continue
            page_name = str(page.get("name") or "Facebook Page").strip()[:160]
            _upsert_meta_social_account(
                db, ctx, platform="Facebook", external_id=page_id, account_name=page_name,
                handle=f"page:{page_id}", access_token=access_token_for_account("Facebook", user_access_token=long_payload["access_token"], page_access_token=page_token), scopes=scopes,
            )
            saved += 1
            instagram = page.get("instagram_business_account")
            if isinstance(instagram, dict) and instagram.get("id"):
                ig_id = str(instagram["id"]).strip()
                username = str(instagram.get("username") or "").strip()
                _upsert_meta_social_account(
                    db, ctx, platform="Instagram", external_id=ig_id,
                    account_name=username or f"Instagram {ig_id}",
                    handle=f"@{username}" if username else f"ig:{ig_id}",
                    access_token=access_token_for_account("Instagram", user_access_token=long_payload["access_token"], page_access_token=page_token), scopes=scopes,
                )
                saved += 1
        if not saved:
            db.rollback()
            return finish("no_pages")
        audit(db, ctx, "integration.meta_connected", "provider", None, {"account_count": saved, "api_version": config["version"]})
        db.commit()
        return finish("connected", saved)
    except (MetaGraphError, CredentialStoreError, CredentialScopeError, TokenVaultError, IntegrityError):
        db.rollback()
        security_logger.warning("meta_oauth_connection_failed organization_id=%s", organization.id)
        return finish("connection_failed")
    except Exception:
        db.rollback()
        security_logger.exception("meta_oauth_connection_unexpected_failure organization_id=%s", organization.id)
        return finish("connection_failed")


@app.get(f"{API_PREFIX}/integrations/meta/accounts/{{account_id}}/media")
async def meta_account_media(
    account_id: str, limit: int = Query(30, ge=1, le=50),
    ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db),
):
    require_read(ctx, "accounts")
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == account_id, SocialAccount.organization_id == ctx.organization.id,
        SocialAccount.platform.in_(("Facebook", "Instagram")),
        SocialAccount.connection_status == "connected", SocialAccount.provider_account_id.is_not(None),
    ))
    if not account:
        raise HTTPException(status_code=404, detail="الحساب غير متصل أو غير موجود في مساحة العمل الحالية.")
    config = get_meta_config()
    if not config:
        raise HTTPException(status_code=503, detail="إعداد Meta غير متاح على هذا الخادم.")
    try:
        credential = load_provider_credential(db, organization_id=ctx.organization.id, social_account_id=account.id)
        if credential is None:
            raise HTTPException(status_code=409, detail="لا توجد بيانات اعتماد مشفرة لهذا الحساب؛ أعد ربط Meta.")
        items = await fetch_account_media(config, account.platform, account.provider_account_id, credential.access_token, limit)
    except HTTPException:
        raise
    except (MetaGraphError, CredentialStoreError, CredentialScopeError, TokenVaultError):
        raise HTTPException(status_code=502, detail="تعذر قراءة المحتوى من Meta. تحقق من صلاحيات التطبيق وصلاحية الربط ثم أعد الاتصال.")
    account.last_synced_at = utcnow()
    audit(db, ctx, "integration.meta_media_read", "social_account", account.id, {"count": len(items)})
    db.commit()
    return {
        "account": {"id": account.id, "platform": account.platform, "account_name": account.account_name, "handle": account.handle},
        "source": "meta_graph_api", "items": items, "fetched_at": utcnow(),
    }


@app.get(f"{API_PREFIX}/social-accounts", response_model=list[SocialAccountOut])
def list_social_accounts(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "accounts")
    return list(db.scalars(select(SocialAccount).where(SocialAccount.organization_id == ctx.organization.id).order_by(SocialAccount.platform, SocialAccount.account_name)).all())

@app.post(f"{API_PREFIX}/social-accounts", response_model=SocialAccountOut, status_code=201)
def create_social_account(data: SocialAccountCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "accounts")
    obj = SocialAccount(organization_id=ctx.organization.id, platform=data.platform, account_name=data.account_name.strip(), handle=(data.handle or "").strip() or None, connection_status="disconnected")
    db.add(obj)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # Avoid exposing SQL errors; most likely the same platform + handle was already added.
        raise HTTPException(status_code=409, detail="هذا الحساب مسجل بالفعل في مساحة العمل") from exc
    audit(db, ctx, "created", "social_account", obj.id, {"platform": obj.platform}); db.commit(); db.refresh(obj)
    return obj

@app.delete(f"{API_PREFIX}/social-accounts/{{account_id}}", status_code=204)
def delete_social_account(account_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "accounts")
    obj = db.scalar(select(SocialAccount).where(SocialAccount.id == account_id, SocialAccount.organization_id == ctx.organization.id))
    if not obj: not_found("الحساب الاجتماعي")
    # Clear linked post destinations explicitly as well as relying on ON DELETE SET NULL,
    # because early local SQLite databases receive compatibility columns without a new FK.
    db.execute(update(Post).where(Post.organization_id == ctx.organization.id, Post.social_account_id == obj.id).values(social_account_id=None))
    # Tokens are intentionally not stored in this MVP. A future per-organization OAuth
    # connection must revoke/disconnect safely and store secrets in a managed vault.
    audit(db, ctx, "deleted", "social_account", obj.id); db.delete(obj); db.commit(); return Response(status_code=204)

def media_out(asset: MediaAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "created_by": asset.created_by,
        "created_at": asset.created_at,
        "download_url": f"{API_PREFIX}/media/{asset.id}/download",
    }


def _short_video_out(item: ShortVideoDraft) -> dict[str, Any]:
    try:
        platforms = json.loads(item.target_platforms or "[]")
        if not isinstance(platforms, list):
            platforms = []
    except (TypeError, ValueError):
        platforms = []
    return {
        "id": item.id, "organization_id": item.organization_id, "title": item.title,
        "caption": item.caption, "media_asset_id": item.media_asset_id,
        "target_platforms": platforms, "aspect_ratio": item.aspect_ratio,
        "duration_seconds": item.duration_seconds, "status": item.status,
        "created_by": item.created_by, "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _validate_video_asset(db: Session, organization_id: str, media_asset_id: str | None, status_value: str) -> MediaAsset | None:
    asset = None
    if media_asset_id:
        asset = db.scalar(select(MediaAsset).where(MediaAsset.id == media_asset_id, MediaAsset.organization_id == organization_id))
        if not asset:
            raise HTTPException(status_code=422, detail="ملف الوسائط غير موجود ضمن مساحة العمل الحالية")
        if not asset.media_type.startswith("video/"):
            raise HTTPException(status_code=422, detail="استوديو الفيديو يقبل ملفات فيديو فقط")
    if status_value == "ready" and asset is None:
        raise HTTPException(status_code=422, detail="يلزم إرفاق فيديو قبل وضع المسودة بحالة جاهزة للمراجعة")
    return asset


@app.get(f"{API_PREFIX}/video-drafts", response_model=list[ShortVideoDraftOut])
def list_short_video_drafts(limit: int = Query(100, ge=1, le=250), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "posts")
    rows = db.scalars(select(ShortVideoDraft).where(ShortVideoDraft.organization_id == ctx.organization.id).order_by(ShortVideoDraft.updated_at.desc()).limit(limit)).all()
    return [_short_video_out(row) for row in rows]


@app.post(f"{API_PREFIX}/video-drafts", response_model=ShortVideoDraftOut, status_code=201)
def create_short_video_draft(data: ShortVideoDraftCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    _validate_video_asset(db, ctx.organization.id, data.media_asset_id, data.status)
    row = ShortVideoDraft(
        organization_id=ctx.organization.id, title=data.title.strip(), caption=data.caption.strip(),
        media_asset_id=data.media_asset_id, target_platforms=json.dumps(data.target_platforms, ensure_ascii=False),
        aspect_ratio=data.aspect_ratio, duration_seconds=data.duration_seconds, status=data.status,
        created_by=ctx.user.id, created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    audit(db, ctx, "created", "short_video_draft", row.id, {"platforms": data.target_platforms, "status": row.status})
    db.commit()
    db.refresh(row)
    return _short_video_out(row)


@app.put(f"{API_PREFIX}/video-drafts/{{draft_id}}", response_model=ShortVideoDraftOut)
def update_short_video_draft(draft_id: str, data: ShortVideoDraftUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    row = db.scalar(select(ShortVideoDraft).where(ShortVideoDraft.id == draft_id, ShortVideoDraft.organization_id == ctx.organization.id))
    if not row:
        not_found("مسودة الفيديو")
    _validate_video_asset(db, ctx.organization.id, data.media_asset_id, data.status)
    row.title = data.title.strip()
    row.caption = data.caption.strip()
    row.media_asset_id = data.media_asset_id
    row.target_platforms = json.dumps(data.target_platforms, ensure_ascii=False)
    row.aspect_ratio = data.aspect_ratio
    row.duration_seconds = data.duration_seconds
    row.status = data.status
    row.updated_at = utcnow()
    audit(db, ctx, "updated", "short_video_draft", row.id, {"platforms": data.target_platforms, "status": row.status})
    db.commit()
    db.refresh(row)
    return _short_video_out(row)


@app.delete(f"{API_PREFIX}/video-drafts/{{draft_id}}", status_code=204)
def delete_short_video_draft(draft_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "posts")
    row = db.scalar(select(ShortVideoDraft).where(ShortVideoDraft.id == draft_id, ShortVideoDraft.organization_id == ctx.organization.id))
    if not row:
        not_found("مسودة الفيديو")
    audit(db, ctx, "deleted", "short_video_draft", row.id, {"title": row.title})
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@app.get(f"{API_PREFIX}/media", response_model=list[MediaAssetOut])
def list_media(limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "media")
    assets = db.scalars(select(MediaAsset).where(MediaAsset.organization_id == ctx.organization.id).order_by(MediaAsset.created_at.desc()).limit(limit).offset(offset)).all()
    return [media_out(asset) for asset in assets]


@app.post(f"{API_PREFIX}/media", response_model=MediaAssetOut, status_code=201)
async def upload_media(file: UploadFile = File(...), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "media")
    original_name = Path(file.filename or "file").name.replace("\\", "_").replace("/", "_")
    original_name = re.sub(r"[^\w.() \-\u0600-\u06FF]", "_", original_name)[:255].strip(" .") or "media-file"
    suffix = Path(original_name).suffix.lower()
    image_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
    video_types = {".mp4": "video/mp4", ".webm": "video/webm"}
    allowed_other = {".pdf": "application/pdf"}
    if suffix not in image_types and suffix not in video_types and suffix not in allowed_other:
        raise HTTPException(status_code=415, detail="نوع الملف غير مسموح. الأنواع المتاحة: JPG وPNG وGIF وWEBP وMP4 وWEBM وPDF")
    limit = MAX_VIDEO_BYTES if suffix in video_types else MAX_IMAGE_BYTES
    content = await file.read(limit + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"حجم الملف يتجاوز الحد المسموح ({limit // (1024 * 1024)} ميجابايت)")
    media_type = image_types.get(suffix) or video_types.get(suffix) or allowed_other.get(suffix)
    if suffix in image_types:
        try:
            with Image.open(io.BytesIO(content)) as image_obj:
                # Limit decompressed dimensions as well as compressed upload size.
                if image_obj.width * image_obj.height > 40_000_000:
                    raise HTTPException(status_code=413, detail="أبعاد الصورة أكبر من الحد الآمن المسموح")
                image_obj.verify()
                actual = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}.get(image_obj.format)
            if actual != image_type_expected(suffix):
                raise HTTPException(status_code=415, detail="امتداد الصورة لا يتوافق مع محتواها")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=415, detail="محتوى الصورة غير صالح أو يتجاوز الحدود الآمنة") from exc
    elif suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="محتوى ملف PDF غير صالح")
    elif suffix == ".mp4" and b"ftyp" not in content[:32]:
        raise HTTPException(status_code=415, detail="محتوى فيديو MP4 غير صالح")
    elif suffix == ".webm" and not content.startswith(b"\x1a\x45\xdf\xa3"):
        raise HTTPException(status_code=415, detail="محتوى فيديو WEBM غير صالح")
    stored = f"{new_id()}{suffix}"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    path = MEDIA_DIR / stored
    path.write_bytes(content)
    asset = MediaAsset(organization_id=ctx.organization.id, original_filename=original_name, stored_filename=stored, media_type=media_type, size_bytes=len(content), created_by=ctx.user.id)
    db.add(asset)
    try:
        db.flush()
        audit(db, ctx, "created", "media_asset", asset.id, {"size_bytes": len(content), "media_type": media_type})
        db.commit()
        db.refresh(asset)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return media_out(asset)


def image_type_expected(suffix: str) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}[suffix]


@app.get(f"{API_PREFIX}/media/{{asset_id}}/download")
def download_media(asset_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "media")
    asset = db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.organization_id == ctx.organization.id))
    if not asset:
        not_found("الملف")
    path = MEDIA_DIR / asset.stored_filename
    if not path.is_file():
        raise HTTPException(status_code=410, detail="الملف غير موجود في التخزين؛ قد يحتاج إلى استعادة نسخة احتياطية")
    return FileResponse(path, media_type=asset.media_type, filename=asset.original_filename, content_disposition_type="attachment", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@app.delete(f"{API_PREFIX}/media/{{asset_id}}", status_code=204)
def delete_media(asset_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "media")
    asset = db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.organization_id == ctx.organization.id))
    if not asset:
        not_found("الملف")
    path = MEDIA_DIR / asset.stored_filename
    audit(db, ctx, "deleted", "media_asset", asset.id, {"original_filename": asset.original_filename})
    db.delete(asset)
    db.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=204)


def _csv_safe_cell(value: Any) -> Any:
    """Prefix spreadsheet formula-leading text while preserving numeric cells."""
    if value is None or isinstance(value, (int, float)):
        return value
    text_value = str(value)
    # Excel/LibreOffice can interpret formula prefixes even after whitespace.
    # Prefix an apostrophe to untrusted text when the first non-space character
    # is one of the spreadsheet formula operators.
    first_significant = text_value.lstrip(" \t\r\n\u00a0")[:1]
    if first_significant in {"=", "+", "-", "@"}:
        return "'" + text_value
    if text_value.startswith(("\t", "\r", "\n")):
        return "'" + text_value
    return text_value


@app.get(f"{API_PREFIX}/exports/contacts.csv")
def export_contacts(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin", "support"})
    require_read(ctx, "contacts")
    contacts = db.scalars(select(Contact).where(Contact.organization_id == ctx.organization.id).order_by(Contact.created_at.asc())).all()
    buffer = io.StringIO(newline="")
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(["الاسم", "الشركة", "البريد الإلكتروني", "الهاتف", "المصدر", "المرحلة", "قيمة الفرصة", "موعد المتابعة", "الملاحظات"])
    for item in contacts:
        writer.writerow([_csv_safe_cell(value) for value in (item.name, item.company, item.email or "", item.phone or "", item.source, item.stage, item.value, item.follow_up_at.isoformat() if item.follow_up_at else "", item.notes)])
    audit(db, ctx, "exported", "contacts", None, {"count": len(contacts)})
    db.commit()
    data = buffer.getvalue().encode("utf-8")
    return Response(content=data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="m-contacts.csv"', "Cache-Control": "private, no-store"})


@app.get(f"{API_PREFIX}/campaigns", response_model=list[CampaignOut])
def list_campaigns(status: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "campaigns")
    stmt = select(Campaign).where(Campaign.organization_id == ctx.organization.id)
    if status:
        stmt = stmt.where(Campaign.status == status)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q[:100]}%"))
    return list(db.scalars(stmt.order_by(Campaign.updated_at.desc()).limit(limit).offset(offset)).all())


@app.post(f"{API_PREFIX}/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(data: CampaignCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "campaigns")
    obj = Campaign(**data.model_dump(), organization_id=ctx.organization.id, created_by=ctx.user.id)
    db.add(obj)
    db.flush()
    audit(db, ctx, "created", "campaign", obj.id, {"name": obj.name, "status": obj.status})
    db.commit()
    db.refresh(obj)
    return obj


@app.put(f"{API_PREFIX}/campaigns/{{campaign_id}}", response_model=CampaignOut)
def update_campaign(campaign_id: str, data: CampaignUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "campaigns")
    obj = db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == ctx.organization.id))
    if not obj:
        not_found("الحملة")
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    audit(db, ctx, "updated", "campaign", obj.id, {"name": obj.name, "status": obj.status})
    db.commit()
    db.refresh(obj)
    return obj


@app.delete(f"{API_PREFIX}/campaigns/{{campaign_id}}", status_code=204)
def delete_campaign(campaign_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "campaigns")
    obj = db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == ctx.organization.id))
    if not obj:
        not_found("الحملة")
    audit(db, ctx, "deleted", "campaign", obj.id)
    db.delete(obj)
    db.commit()
    return Response(status_code=204)


@app.post(f"{API_PREFIX}/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(data: ConversationCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "inbox")
    if data.contact_id:
        contact = db.scalar(select(Contact).where(Contact.id == data.contact_id, Contact.organization_id == ctx.organization.id))
        if not contact:
            not_found("العميل المرتبط بالمحادثة")
    obj = Conversation(organization_id=ctx.organization.id, channel=data.channel, contact_id=data.contact_id, status=data.status)
    db.add(obj)
    db.flush()
    audit(db, ctx, "created", "conversation", obj.id, {"channel": obj.channel, "local_only": True})
    db.commit()
    db.refresh(obj)
    return obj


@app.patch(f"{API_PREFIX}/conversations/{{conversation_id}}", response_model=ConversationOut)
def update_conversation(conversation_id: str, data: ConversationUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "inbox")
    obj = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.organization_id == ctx.organization.id))
    if not obj:
        not_found("المحادثة")
    if data.contact_id:
        contact = db.scalar(select(Contact).where(Contact.id == data.contact_id, Contact.organization_id == ctx.organization.id))
        if not contact:
            not_found("العميل المرتبط بالمحادثة")
    obj.status = data.status
    obj.contact_id = data.contact_id
    audit(db, ctx, "updated", "conversation", obj.id, {"status": obj.status, "local_only": True})
    db.commit()
    db.refresh(obj)
    return obj


@app.post(f"{API_PREFIX}/conversations/{{conversation_id}}/messages", response_model=MessageOut, status_code=201)
async def create_local_message(conversation_id: str, data: MessageCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_write(ctx, "inbox")
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.organization_id == ctx.organization.id,
    ))
    if not conversation:
        not_found("المحادثة")

    body = data.body.strip()
    if conversation.channel == "WhatsApp" and data.direction == "outbound":
        config = get_whatsapp_config()
        if config is None:
            raise HTTPException(status_code=503, detail="إعداد WhatsApp Business غير مكتمل على الخادم.")
        account = db.scalar(select(SocialAccount).where(
            SocialAccount.organization_id == ctx.organization.id,
            SocialAccount.platform == "WhatsApp",
            SocialAccount.connection_status == "connected",
            SocialAccount.provider_account_id.is_not(None),
        ))
        if account is None:
            raise HTTPException(status_code=409, detail="تحقق من رقم WhatsApp Business أولًا من صفحة التكاملات.")
        if not conversation.external_id or not re.fullmatch(r"[0-9]{7,20}", conversation.external_id):
            raise HTTPException(status_code=422, detail="المحادثة لا تحتوي رقم WhatsApp صالحًا بصيغة دولية.")
        try:
            credential = load_provider_credential(
                db, organization_id=ctx.organization.id, social_account_id=account.id,
            )
        except (CredentialStoreError, CredentialScopeError, TokenVaultError) as exc:
            raise HTTPException(status_code=409, detail="تعذر فك اعتماد WhatsApp المشفر بأمان؛ أعد التحقق من رقم الأعمال.") from exc
        if credential is None:
            raise HTTPException(status_code=409, detail="لا يوجد اعتماد WhatsApp مشفر لهذا الرقم؛ أعد التحقق من رقم الأعمال.")
        try:
            delivery = await whatsapp_send_text(
                graph_version=config["graph_version"],
                phone_number_id=account.provider_account_id,
                access_token=credential.access_token,
                recipient=conversation.external_id,
                text=body,
            )
        except WhatsAppDeliveryUnknown as exc:
            now = utcnow()
            message = Message(
                organization_id=ctx.organization.id, conversation_id=conversation.id,
                direction="outbound", body=body, delivery_status="delivery_unknown", created_at=now,
            )
            conversation.last_message_at = now
            if conversation.status == "closed":
                conversation.status = "open"
            db.add(message)
            db.flush()
            audit(db, ctx, "whatsapp.message_outcome_unknown", "message", message.id, {
                "conversation_id": conversation.id, "account_id": account.id,
            })
            db.commit()
            db.refresh(message)
            raise HTTPException(status_code=502, detail="أرسل M الطلب، لكن WhatsApp لم يؤكد النتيجة. افحص المحادثة قبل أي إعادة محاولة.") from exc
        except WhatsAppCloudError as exc:
            raise HTTPException(status_code=502, detail=f"رفض WhatsApp إرسال الرسالة: {str(exc)[:300]}") from exc

        now = utcnow()
        message = Message(
            organization_id=ctx.organization.id, conversation_id=conversation.id,
            direction="outbound", body=body,
            provider_message_id=delivery["message_id"], delivery_status="sent", created_at=now,
        )
        conversation.last_message_at = now
        if conversation.status == "closed":
            conversation.status = "open"
        db.add(message)
        db.flush()
        audit(db, ctx, "whatsapp.message_sent", "message", message.id, {
            "conversation_id": conversation.id, "account_id": account.id,
            "provider_message_id": delivery["message_id"],
        })
        db.commit()
        db.refresh(message)
        return message

    # Non-WhatsApp channels remain local-only until their inbound/outbound adapters are implemented.
    now = utcnow()
    message = Message(
        organization_id=ctx.organization.id, conversation_id=conversation.id,
        direction=data.direction, body=body, delivery_status="local_only", created_at=now,
    )
    conversation.last_message_at = now
    if conversation.status == "closed":
        conversation.status = "open"
    db.add(message)
    db.flush()
    audit(db, ctx, "created", "message", message.id, {
        "conversation_id": conversation.id, "delivery_status": "local_only",
    })
    db.commit()
    db.refresh(message)
    return message


@app.get(f"{API_PREFIX}/conversations", response_model=list[ConversationOut])
def list_conversations(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "inbox")
    return list(db.scalars(select(Conversation).where(Conversation.organization_id == ctx.organization.id).order_by(Conversation.last_message_at.desc().nullslast()).limit(200)).all())

@app.get(f"{API_PREFIX}/conversations/{{conversation_id}}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_read(ctx, "inbox")
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.organization_id == ctx.organization.id))
    if not conversation: not_found("المحادثة")
    return list(db.scalars(select(Message).where(Message.conversation_id == conversation_id, Message.organization_id == ctx.organization.id).order_by(Message.created_at.asc()).limit(500)).all())

@app.get(f"{API_PREFIX}/audit-logs")
def list_audit_logs(limit: int = Query(100, ge=1, le=250), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)):
    require_roles(ctx, {"owner", "admin"})
    rows = db.scalars(select(AuditLog).where(AuditLog.organization_id == ctx.organization.id).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    def safe_details(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return [{"id": x.id, "user_id": x.user_id, "action": x.action, "entity_type": x.entity_type, "entity_id": x.entity_id, "details": safe_details(x.details), "created_at": x.created_at} for x in rows]

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
