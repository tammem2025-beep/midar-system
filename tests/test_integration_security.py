"""Security primitives for provider credentials, adapters, and webhook authenticity."""
from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.security_tokens import (
    TokenVaultConfigurationError,
    TokenVaultError,
    decrypt_provider_token,
    encrypt_provider_token,
    generate_provider_encryption_key,
)
from app.integrations.webhook_security import verify_meta_signature, verify_telegram_webhook_secret
from app.integrations.registry import get_connector


def test_provider_token_round_trip_and_no_plaintext_fallback(monkeypatch):
    key = generate_provider_encryption_key()
    monkeypatch.setenv("PROVIDER_TOKEN_ENCRYPTION_KEY", key)
    raw = "access-token-sensitive-value-123"
    encrypted = encrypt_provider_token(raw)
    assert encrypted.startswith("fernet:v1:")
    assert raw not in encrypted
    assert decrypt_provider_token(encrypted) == raw
    with pytest.raises(TokenVaultError):
        decrypt_provider_token(raw)


def test_provider_token_vault_fails_closed_when_key_missing_or_invalid(monkeypatch):
    monkeypatch.delenv("PROVIDER_TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(TokenVaultConfigurationError):
        encrypt_provider_token("not-to-be-stored-in-plaintext")
    monkeypatch.setenv("PROVIDER_TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(TokenVaultConfigurationError):
        encrypt_provider_token("secret")
    monkeypatch.setenv("PROVIDER_TOKEN_ENCRYPTION_KEY", generate_provider_encryption_key() + "é")
    with pytest.raises(TokenVaultConfigurationError):
        encrypt_provider_token("secret")


def test_provider_token_rejects_wrong_key_and_tampering(monkeypatch):
    first = generate_provider_encryption_key()
    second = generate_provider_encryption_key()
    ciphertext = encrypt_provider_token("a-provider-token", key=first)
    with pytest.raises(TokenVaultError):
        decrypt_provider_token(ciphertext, key=second)
    tampered = ciphertext[:-4] + "AAAA"
    with pytest.raises(TokenVaultError):
        decrypt_provider_token(tampered, key=first)
    with pytest.raises(TokenVaultError):
        encrypt_provider_token("")


def test_meta_webhook_signature_matches_documented_hmac_sha256_vector():
    body = b"Hello, World!"
    secret = "It's a Secret to Everybody"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"
    assert verify_meta_signature(body, header, secret) is True
    assert verify_meta_signature(body + b"!", header, secret) is False
    assert verify_meta_signature(body, "sha1=" + digest, secret) is False
    assert verify_meta_signature(body, None, secret) is False
    assert verify_meta_signature(body, header, "") is False


def test_telegram_webhook_secret_requires_valid_header_and_constant_time_match():
    assert verify_telegram_webhook_secret("valid_Secret-123", "valid_Secret-123") is True
    assert verify_telegram_webhook_secret("wrong_secret", "valid_Secret-123") is False
    assert verify_telegram_webhook_secret(None, "valid_Secret-123") is False
    assert verify_telegram_webhook_secret("contains space", "contains space") is False
    assert verify_telegram_webhook_secret("x" * 257, "x" * 257) is False


def test_provider_registry_does_not_turn_catalog_entries_into_live_connectors():
    async def verify(_token: str, _target: str):
        return {"verified": True}

    async def publish(_token: str, _target: str, _text: str):
        return {"published": True}

    telegram = get_connector("Telegram", telegram_verify_fn=verify, telegram_publish_fn=publish)
    assert telegram is not None
    assert telegram.capabilities.verify_destination is True
    assert telegram.capabilities.publish_text is True
    assert telegram.capabilities.publish_media is False
    assert telegram.capabilities.account_authorization is False
    assert telegram.capabilities.inbound_webhooks is False
    assert get_connector("Meta", telegram_verify_fn=verify, telegram_publish_fn=publish) is None
    assert get_connector("Instagram", telegram_verify_fn=verify, telegram_publish_fn=publish) is None


def test_sqlite_credential_migration_is_idempotent_on_existing_schema(tmp_path):
    """The additive SQLite migration can run twice after legacy tables exist."""
    import sqlite3
    from sqlalchemy import create_engine, inspect
    from app.db import Base
    from app import models  # noqa: F401 - register model metadata

    database_path = tmp_path / "migration-test.db"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE integration_credentials")
            connection.exec_driver_sql("DROP TABLE provider_oauth_bindings")

        migration_path = Path(__file__).resolve().parents[1] / "backend" / "migrations" / "sqlite" / "0160_integration_credentials.sql"
        sql = migration_path.read_text(encoding="utf-8")
        with sqlite3.connect(database_path) as raw:
            raw.executescript(sql)
            raw.executescript(sql)

        tables = set(inspect(engine).get_table_names())
        assert "integration_credentials" in tables
        assert "provider_oauth_bindings" in tables
        credential_columns = {item["name"] for item in inspect(engine).get_columns("integration_credentials")}
        assert {"organization_id", "social_account_id", "access_token_ciphertext", "refresh_token_ciphertext", "key_format"} <= credential_columns
    finally:
        engine.dispose()
