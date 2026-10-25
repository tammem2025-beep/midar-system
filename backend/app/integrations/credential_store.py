"""Tenant-scoped encrypted storage for verified provider OAuth credentials.

This is an internal service, not a public HTTP endpoint. Call it only after a
provider-specific OAuth callback has verified state/PKCE and validated the remote
account identity. Meta OAuth is implemented in the API routes; successful linking still requires developer credentials and approved permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, IntegrationCredential, Membership, SocialAccount, User, utcnow, new_id
from ..security_tokens import decrypt_provider_token, encrypt_provider_token


class CredentialStoreError(RuntimeError):
    """Credential storage operation was rejected safely."""


class CredentialScopeError(CredentialStoreError):
    """Requested workspace, social account, actor, or provider did not match."""


@dataclass(frozen=True, slots=True)
class ProviderCredentialMaterial:
    provider: str
    access_token: str
    refresh_token: str | None
    token_type: str
    scopes: tuple[str, ...]
    expires_at: datetime | None


def _require_connection_authority(db: Session, *, organization_id: str, actor_user_id: str) -> None:
    actor = db.get(User, actor_user_id)
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == organization_id,
        Membership.user_id == actor_user_id,
    ))
    if not actor or not actor.is_active or membership is None or membership.role not in {"owner", "admin"}:
        raise CredentialScopeError("An active workspace owner or administrator is required to manage provider credentials.")


def store_provider_credential(
    db: Session,
    *,
    organization_id: str,
    social_account_id: str,
    actor_user_id: str,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_type: str = "Bearer",
    scopes: list[str] | tuple[str, ...] = (),
    expires_at: datetime | None = None,
) -> IntegrationCredential:
    """Insert/update ciphertext after identity verification; caller owns transaction commit."""
    _require_connection_authority(db, organization_id=organization_id, actor_user_id=actor_user_id)
    clean_provider = (provider or "").strip()
    if not clean_provider or len(clean_provider) > 32:
        raise CredentialStoreError("Provider name is invalid.")
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == social_account_id,
        SocialAccount.organization_id == organization_id,
    ))
    if account is None or account.platform.casefold() != clean_provider.casefold():
        raise CredentialScopeError("Social account was not found in this workspace for the requested provider.")
    # Store the canonical platform spelling used by the SocialAccount row.
    clean_provider = account.platform
    if not account.provider_account_id or account.connection_status != "connected":
        raise CredentialStoreError("The remote account must be verified before credentials can be stored.")
    if (
        not isinstance(scopes, (list, tuple)) or len(scopes) > 256
        or any(not isinstance(item, str) or not item.strip() or len(item) > 200 for item in scopes)
    ):
        raise CredentialStoreError("Provider scopes are invalid or exceed the supported count.")
    clean_scopes = sorted(set(item.strip() for item in scopes))
    if sum(len(scope) for scope in clean_scopes) > 16_384:
        raise CredentialStoreError("Provider scopes exceed the supported total size.")
    token_type_clean = (token_type or "Bearer").strip()
    if not token_type_clean or len(token_type_clean) > 32 or any(ord(char) < 33 or ord(char) > 126 for char in token_type_clean):
        raise CredentialStoreError("Token type is invalid.")
    if expires_at is not None:
        from datetime import timezone
        expiry = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
        if expiry <= utcnow():
            raise CredentialStoreError("Expired provider credentials must not be stored as active.")

    # Encrypt before touching ORM state: missing/bad keys fail closed without partial writes.
    access_cipher = encrypt_provider_token(access_token)
    refresh_cipher = encrypt_provider_token(refresh_token) if refresh_token else None
    row = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.organization_id == organization_id,
        IntegrationCredential.social_account_id == social_account_id,
    ))
    if row is None:
        row = IntegrationCredential(
            id=new_id(), organization_id=organization_id, social_account_id=social_account_id,
            provider=clean_provider, access_token_ciphertext=access_cipher,
            refresh_token_ciphertext=refresh_cipher, token_type=token_type_clean,
            scopes_json=json.dumps(clean_scopes, separators=(",", ":")), expires_at=expires_at,
            key_format="fernet:v1", status="active", created_by=actor_user_id,
        )
        db.add(row)
    else:
        row.provider = clean_provider
        row.access_token_ciphertext = access_cipher
        row.refresh_token_ciphertext = refresh_cipher
        row.token_type = token_type_clean
        row.scopes_json = json.dumps(clean_scopes, separators=(",", ":"))
        row.expires_at = expires_at
        row.key_format = "fernet:v1"
        row.status = "active"
        row.updated_at = utcnow()

    # Audit metadata only; never persist token values in details.
    db.add(AuditLog(
        organization_id=organization_id, user_id=actor_user_id,
        action="integration.credential_stored", entity_type="social_account",
        entity_id=social_account_id,
        details=json.dumps({"provider": clean_provider, "scope_count": len(clean_scopes), "encrypted": True}, separators=(",", ":")),
    ))
    db.flush()
    return row


def load_provider_credential(
    db: Session, *, organization_id: str, social_account_id: str,
) -> ProviderCredentialMaterial | None:
    """Load/decrypt only a credential belonging to the supplied workspace/account."""
    row = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.organization_id == organization_id,
        IntegrationCredential.social_account_id == social_account_id,
        IntegrationCredential.status == "active",
    ))
    if row is None:
        return None
    # Also re-check the linked social account tenant/provider relationship, not only the stored row.
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == row.social_account_id,
        SocialAccount.organization_id == organization_id,
        SocialAccount.platform == row.provider,
        SocialAccount.connection_status == "connected",
    ))
    if account is None:
        raise CredentialScopeError("Credential account scope is inconsistent; access is denied.")
    if row.key_format != "fernet:v1":
        raise CredentialStoreError("Stored provider credential encryption format is unsupported.")
    try:
        scopes = json.loads(row.scopes_json)
        if not isinstance(scopes, list) or any(not isinstance(item, str) for item in scopes):
            raise ValueError("invalid scopes")
        return ProviderCredentialMaterial(
            provider=row.provider,
            access_token=decrypt_provider_token(row.access_token_ciphertext),
            refresh_token=decrypt_provider_token(row.refresh_token_ciphertext) if row.refresh_token_ciphertext else None,
            token_type=row.token_type, scopes=tuple(scopes), expires_at=row.expires_at,
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CredentialStoreError("Stored provider credential metadata is invalid.") from exc


def remove_provider_credential(
    db: Session, *, organization_id: str, social_account_id: str, actor_user_id: str,
) -> bool:
    """Remove local ciphertext only; provider-side revocation is a separate adapter operation."""
    _require_connection_authority(db, organization_id=organization_id, actor_user_id=actor_user_id)
    row = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.organization_id == organization_id,
        IntegrationCredential.social_account_id == social_account_id,
    ))
    if row is None:
        return False
    provider = row.provider
    account = db.scalar(select(SocialAccount).where(
        SocialAccount.id == social_account_id,
        SocialAccount.organization_id == organization_id,
        SocialAccount.platform == provider,
    ))
    if account is not None:
        account.connection_status = "disconnected"
        account.provider_account_id = None
        account.last_synced_at = None
    db.add(AuditLog(
        organization_id=organization_id, user_id=actor_user_id,
        action="integration.credential_removed_locally", entity_type="social_account",
        entity_id=social_account_id,
        details=json.dumps({"provider": provider, "provider_revocation_performed": False}, separators=(",", ":")),
    ))
    db.delete(row)
    db.flush()
    return True
