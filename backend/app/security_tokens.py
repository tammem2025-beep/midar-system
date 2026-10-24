"""Fail-closed encryption helpers for third-party provider credentials.

Ciphertext is version-prefixed to prevent legacy/plaintext values from being accepted.
This module never falls back to plaintext and never logs tokens or encryption keys.
"""
from __future__ import annotations

import os
from cryptography.fernet import Fernet, InvalidToken

_FORMAT_PREFIX = "fernet:v1:"
_MAX_SECRET_LENGTH = 64 * 1024
_MAX_ENVELOPE_LENGTH = 1024 * 1024
_ENV_KEY_NAME = "PROVIDER_TOKEN_ENCRYPTION_KEY"


class TokenVaultError(RuntimeError):
    """Base error for secure token encryption/decryption failures."""


class TokenVaultConfigurationError(TokenVaultError):
    """Encryption key is missing or malformed; secure operation must stop."""


def generate_provider_encryption_key() -> str:
    """Generate a new Fernet key for operator setup; never call on every app start."""
    return Fernet.generate_key().decode("ascii")


def _cipher(key: str | bytes | None = None) -> Fernet:
    raw = key if key is not None else os.getenv(_ENV_KEY_NAME)
    if isinstance(raw, str):
        try:
            raw_bytes = raw.encode("ascii")
        except UnicodeEncodeError as exc:
            raise TokenVaultConfigurationError(
                f"{_ENV_KEY_NAME} must be an ASCII Fernet key."
            ) from exc
    elif isinstance(raw, bytes):
        raw_bytes = raw
    else:
        raw_bytes = b""
    if not raw_bytes:
        raise TokenVaultConfigurationError(
            f"{_ENV_KEY_NAME} is not configured; refusing to store provider tokens without encryption."
        )
    try:
        return Fernet(raw_bytes)
    except (TypeError, ValueError) as exc:
        raise TokenVaultConfigurationError(
            f"{_ENV_KEY_NAME} is invalid; provide a Fernet-compatible key."
        ) from exc


def encrypt_provider_token(token: str, *, key: str | bytes | None = None) -> str:
    """Encrypt a provider token and return a versioned envelope suitable for DB storage."""
    if not isinstance(token, str) or not token or len(token) > _MAX_SECRET_LENGTH:
        raise TokenVaultError("Provider token is empty or exceeds the supported size.")
    encrypted = _cipher(key).encrypt(token.encode("utf-8")).decode("ascii")
    return _FORMAT_PREFIX + encrypted


def decrypt_provider_token(envelope: str, *, key: str | bytes | None = None) -> str:
    """Decrypt only recognized ciphertext; unmarked/plaintext values are rejected."""
    if not isinstance(envelope, str) or not envelope or len(envelope) > _MAX_ENVELOPE_LENGTH:
        raise TokenVaultError("Provider token envelope is invalid.")
    if not envelope.startswith(_FORMAT_PREFIX):
        raise TokenVaultError("Provider token envelope format is unsupported; plaintext fallback is forbidden.")
    payload = envelope[len(_FORMAT_PREFIX):]
    try:
        return _cipher(key).decrypt(payload.encode("ascii")).decode("utf-8")
    except TokenVaultConfigurationError:
        raise
    except (InvalidToken, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise TokenVaultError("Provider token could not be decrypted with the configured key.") from exc
