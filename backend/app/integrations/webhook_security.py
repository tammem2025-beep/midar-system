"""Provider webhook authenticity checks. These helpers do not expose an HTTP route."""
from __future__ import annotations

import hashlib
import hmac
import re

_META_SIGNATURE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")
_TELEGRAM_SECRET = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str | None) -> bool:
    """Validate Meta X-Hub-Signature-256 against the exact raw body bytes.

    Call before parsing JSON and only with the correct app secret for the subscribed
    product. The same verifier is suitable for Meta products whose documented signing
    scheme is HMAC-SHA256; secret selection remains product/configuration-specific.
    """
    if not isinstance(raw_body, bytes) or not isinstance(app_secret, str) or not app_secret:
        return False
    if not isinstance(signature_header, str):
        return False
    match = _META_SIGNATURE.fullmatch(signature_header.strip())
    if not match:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(match.group(1).lower(), expected)


def verify_telegram_webhook_secret(header_value: str | None, expected_secret: str | None) -> bool:
    """Validate Telegram's X-Telegram-Bot-Api-Secret-Token header."""
    if not isinstance(header_value, str) or not isinstance(expected_secret, str):
        return False
    if not _TELEGRAM_SECRET.fullmatch(header_value) or not _TELEGRAM_SECRET.fullmatch(expected_secret):
        return False
    return hmac.compare_digest(header_value, expected_secret)
