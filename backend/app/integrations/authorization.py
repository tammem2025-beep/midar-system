"""Reusable, one-time OAuth transaction service for future social-account connectors.

This service intentionally does not talk to any provider, exchange codes, or expose an
HTTP endpoint. A provider route must still enforce its registered exact redirect URI,
request minimum scopes, exchange the code server-side, validate the provider identity,
and only then store credentials using credential_store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AuditLog, Membership, OAuthTransaction, Organization, ProviderOAuthBinding, User, utcnow

_PROVIDER_KEY = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_ALLOWED_PURPOSES = {"login", "setup", "link", "identity_link", "connect"}


class AuthorizationTransactionError(RuntimeError):
    """A safe OAuth rejection with a non-sensitive reason code for logs/tests."""

    def __init__(self, message: str, *, reason: str = "invalid_state", cleanup_performed: bool = False):
        super().__init__(message)
        self.reason = reason
        # Some rejection paths deliberately delete an expired/revoked transaction.
        # Their caller must commit this cleanup rather than rolling it back.
        self.cleanup_performed = cleanup_performed


@dataclass(frozen=True, slots=True)
class AuthorizationChallenge:
    provider: str
    purpose: str
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: str
    browser_binding: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConsumedAuthorization:
    provider: str
    purpose: str
    user_id: str | None
    organization_id: str | None
    auth_version: int | None
    nonce: str
    code_verifier: str


def _hash_state(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _hash_browser_binding(binding: str) -> str:
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_authorization_transaction(
    db: Session,
    *,
    provider: str,
    purpose: str,
    user_id: str | None = None,
    organization_id: str | None = None,
    auth_version: int | None = None,
    ttl_seconds: int = 600,
) -> AuthorizationChallenge:
    """Create hashed state + nonce + PKCE S256 transaction. Caller commits promptly."""
    normalized_provider = (provider or "").strip().casefold()
    if not _PROVIDER_KEY.fullmatch(normalized_provider):
        raise AuthorizationTransactionError("Provider identifier is invalid.", reason="invalid_provider")
    if purpose not in _ALLOWED_PURPOSES:
        raise AuthorizationTransactionError("Authorization purpose is invalid.", reason="invalid_purpose")
    ttl = max(60, min(int(ttl_seconds), 900))

    if purpose in {"link", "identity_link", "connect"}:
        if not user_id or not organization_id:
            raise AuthorizationTransactionError("Account linking requires an authenticated user and workspace.", reason="invalid_context")
        user = db.get(User, user_id)
        organization = db.get(Organization, organization_id)
        membership = db.scalar(select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
        ))
        if not user or not user.is_active or not organization or membership is None:
            raise AuthorizationTransactionError("Account linking context is not valid.", reason="invalid_context")
        if purpose in {"link", "connect"} and membership.role not in {"owner", "admin"}:
            raise AuthorizationTransactionError("Only a workspace owner or administrator may link a social account.", reason="insufficient_role")
        if auth_version is not None and int(auth_version) != int(user.auth_version or 0):
            raise AuthorizationTransactionError("User authentication state changed; start authorization again.", reason="auth_changed")
        auth_version = int(user.auth_version or 0)

    raw_state = secrets.token_urlsafe(32)
    browser_binding = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    # token_urlsafe(64) yields a PKCE verifier within RFC 7636's 43..128 character range.
    verifier = secrets.token_urlsafe(64)
    expires_at = utcnow() + timedelta(seconds=ttl)
    row = OAuthTransaction(
        state_hash=_hash_state(raw_state), provider=normalized_provider, purpose=purpose,
        nonce=nonce, code_verifier=verifier, user_id=user_id,
        organization_id=organization_id, auth_version=auth_version,
        created_at=utcnow(), expires_at=expires_at,
    )
    db.add(row)
    db.add(ProviderOAuthBinding(
        state_hash=row.state_hash,
        browser_binding_hash=_hash_browser_binding(browser_binding),
        created_at=utcnow(),
    ))
    if purpose in {"link", "identity_link", "connect"} and user_id and organization_id:
        db.add(AuditLog(
            organization_id=organization_id, user_id=user_id,
            action="integration.authorization_started", entity_type="provider",
            details=json.dumps({"provider": normalized_provider, "purpose": purpose}, separators=(",", ":")),
        ))
    db.flush()
    return AuthorizationChallenge(
        provider=normalized_provider, purpose=purpose, state=raw_state, nonce=nonce,
        code_verifier=verifier, code_challenge=_pkce_s256(verifier),
        code_challenge_method="S256", browser_binding=browser_binding, expires_at=expires_at,
    )


def cleanup_expired_authorization_transactions(db: Session) -> int:
    """Delete expired OAuth transactions and their browser bindings in the caller transaction.

    Returns the number of transactions removed. This is safe to call before starting
    another flow and does not log state values, verifier material, or cookies.
    """
    now = utcnow()
    expired_states = select(OAuthTransaction.state_hash).where(OAuthTransaction.expires_at <= now)
    db.execute(delete(ProviderOAuthBinding).where(ProviderOAuthBinding.state_hash.in_(expired_states)))
    result = db.execute(delete(OAuthTransaction).where(OAuthTransaction.expires_at <= now))
    db.flush()
    return max(0, int(result.rowcount or 0))


def consume_authorization_transaction(
    db: Session,
    *,
    provider: str,
    purpose: str,
    state: str,
    browser_binding: str,
) -> ConsumedAuthorization:
    """Validate and mark a transaction one-use within the caller's current DB transaction.

    The caller MUST commit immediately after this function returns and before making the
    provider token request. Never keep the state transaction live across network I/O.
    """
    normalized_provider = (provider or "").strip().casefold()
    if (not state or len(state) > 512 or len(browser_binding) > 512
            or not _PROVIDER_KEY.fullmatch(normalized_provider) or purpose not in _ALLOWED_PURPOSES):
        raise AuthorizationTransactionError("Authorization state is invalid.", reason="invalid_request")
    row = db.get(OAuthTransaction, _hash_state(state))
    if row is None:
        raise AuthorizationTransactionError("Authorization state is missing or was already used.", reason="missing_transaction")
    if row.provider != normalized_provider or row.purpose != purpose:
        raise AuthorizationTransactionError("Authorization state does not match this provider or action.", reason="transaction_mismatch")
    browser_row = db.get(ProviderOAuthBinding, row.state_hash)
    if browser_row is None or not secrets.compare_digest(
        browser_row.browser_binding_hash, _hash_browser_binding(browser_binding),
    ):
        raise AuthorizationTransactionError("Authorization state is not bound to this browser session.", reason="browser_binding_mismatch")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        # Explicitly remove the binding too; do not depend solely on database-level
        # ON DELETE CASCADE being enabled in every local/test SQLite connection.
        db.execute(delete(ProviderOAuthBinding).where(ProviderOAuthBinding.state_hash == row.state_hash))
        db.delete(row)
        db.flush()
        raise AuthorizationTransactionError(
            "Authorization state expired; restart the flow.", reason="expired", cleanup_performed=True,
        )

    if row.purpose in {"link", "identity_link", "connect"}:
        user = db.get(User, row.user_id) if row.user_id else None
        organization = db.get(Organization, row.organization_id) if row.organization_id else None
        membership = db.scalar(select(Membership).where(
            Membership.user_id == row.user_id,
            Membership.organization_id == row.organization_id,
        )) if row.user_id and row.organization_id else None
        if (
            not user or not user.is_active or not organization or membership is None
            or (row.purpose in {"link", "connect"} and membership.role not in {"owner", "admin"})
            or int(user.auth_version or 0) != int(row.auth_version or 0)
        ):
            db.execute(delete(ProviderOAuthBinding).where(ProviderOAuthBinding.state_hash == row.state_hash))
            db.delete(row)
            db.flush()
            raise AuthorizationTransactionError(
                "Authorization context changed; restart the flow.",
                reason="authorization_context_changed", cleanup_performed=True,
            )

    result = ConsumedAuthorization(
        provider=row.provider, purpose=row.purpose, user_id=row.user_id,
        organization_id=row.organization_id, auth_version=row.auth_version,
        nonce=row.nonce, code_verifier=row.code_verifier,
    )
    # A conditional SQL DELETE is the one-time claim. If two callbacks race, only
    # one may observe rowcount=1 and proceed to the provider network request.
    claimed = db.execute(delete(OAuthTransaction).where(
        OAuthTransaction.state_hash == row.state_hash,
        OAuthTransaction.provider == normalized_provider,
        OAuthTransaction.purpose == purpose,
    ))
    if int(claimed.rowcount or 0) != 1:
        raise AuthorizationTransactionError(
            "Authorization state was already consumed; restart the flow.", reason="already_used",
        )
    db.execute(delete(ProviderOAuthBinding).where(ProviderOAuthBinding.state_hash == row.state_hash))
    db.flush()
    if result.purpose in {"link", "identity_link", "connect"} and result.user_id and result.organization_id:
        db.add(AuditLog(
            organization_id=result.organization_id, user_id=result.user_id,
            action="integration.authorization_state_consumed", entity_type="provider",
            details=json.dumps({"provider": result.provider, "purpose": result.purpose}, separators=(",", ":")),
        ))
        db.flush()
    return result
