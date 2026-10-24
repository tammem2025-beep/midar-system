import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

APP_ENV = os.getenv("APP_ENV", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret-before-any-real-use")
if APP_ENV == "production" and (SECRET_KEY == "dev-only-change-this-secret-before-any-real-use" or len(SECRET_KEY) < 32):
    raise RuntimeError("In production, set a random SECRET_KEY of at least 32 characters.")
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "43200"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_text, salt_text, digest_text = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        if rounds < 100_000 or rounds > 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_access_token(subject: str, organization_id: str, auth_version: int = 0) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "org": organization_id, "ver": auth_version, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    left = _b64(json.dumps(header, separators=(",", ":")).encode())
    right = _b64(json.dumps(payload, separators=(",", ":")).encode())
    message = f"{left}.{right}".encode()
    signature = _b64(hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest())
    return f"{left}.{right}.{signature}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        if len(token) > 8192:
            return None
        left, right, signature = token.split(".", 2)
        message = f"{left}.{right}".encode()
        expected = _b64(hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        header = json.loads(base64.urlsafe_b64decode(left + "=" * (-len(left) % 4)))
        payload = json.loads(base64.urlsafe_b64decode(right + "=" * (-len(right) % 4)))
        if header.get("alg") != "HS256" or int(payload.get("exp", 0)) <= int(time.time()):
            return None
        if not payload.get("sub") or not payload.get("org"):
            return None
        return payload
    except Exception:
        return None
