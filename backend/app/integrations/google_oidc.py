"""Google OpenID Connect authorization-code flow helpers.

This module intentionally requests only identity scopes (openid, email, profile).
Google API access such as YouTube or Drive must use a separate, feature-specific
OAuth consent flow with its own least-privilege scopes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from urllib.parse import urlencode, urlparse

import httpx

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_IDENTITY_SCOPES = ("openid", "email", "profile")


class GoogleOIDCError(RuntimeError):
    """A safe, user-displayable Google OIDC error without secrets or raw provider data."""


def get_google_config() -> dict[str, str] | None:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if not (client_id and client_secret and redirect_uri):
        return None
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment:
        return None
    if os.getenv("APP_ENV", "development").lower() == "production":
        if parsed.scheme != "https":
            return None
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return None
    elif parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        # Never allow an insecure public callback, even in development.
        return None
    return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def make_authorization_url(config: dict[str, str], state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_IDENTITY_SCOPES),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_authorization_code(config: dict[str, str], code: str, code_verifier: str) -> str:
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as client:
            response = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uri": config["redirect_uri"],
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200:
            raise GoogleOIDCError("تعذر إكمال التحقق لدى Google. حاول بدء تسجيل الدخول من جديد.")
        body = response.json()
        id_token = body.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise GoogleOIDCError("لم يُرجع Google رمز هوية صالحًا.")
        return id_token
    except GoogleOIDCError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise GoogleOIDCError("تعذر الاتصال بخدمة تسجيل الدخول لدى Google.") from exc


def verify_google_id_token(id_token: str, client_id: str, expected_nonce: str) -> dict:
    """Verify signature, issuer, audience, time claims, verified email and nonce."""
    if not id_token or len(id_token) > 16384:
        raise GoogleOIDCError("رمز هوية Google غير صالح.")
    try:
        import jwt
        from jwt import PyJWKClient
        jwks = PyJWKClient(GOOGLE_JWKS_URL, cache_jwk_set=True, lifespan=300, timeout=5)
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=list(GOOGLE_ISSUERS),
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            leeway=60,
        )
    except ImportError as exc:
        raise GoogleOIDCError("مكتبة التحقق من Google غير مثبتة. نفّذ تثبيت متطلبات Backend ثم حاول مجددًا.") from exc
    except Exception as exc:
        raise GoogleOIDCError("تعذر التحقق من هوية Google أو انتهت صلاحية محاولة الدخول.") from exc
    if not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise GoogleOIDCError("فشل التحقق الأمني لمحاولة تسجيل الدخول. ابدأ من جديد.")
    email_verified = claims.get("email_verified")
    if email_verified is not True and str(email_verified).lower() != "true":
        raise GoogleOIDCError("يجب استخدام حساب Google ببريد إلكتروني موثّق.")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise GoogleOIDCError("لم يُرجع Google معرّف مستخدم صالحًا.")
    if not isinstance(claims.get("email"), str) or "@" not in claims["email"]:
        raise GoogleOIDCError("لم يُرجع Google بريدًا إلكترونيًا صالحًا.")
    if claims.get("azp") and claims["azp"] != client_id:
        raise GoogleOIDCError("رمز الهوية صادر لتطبيق مختلف.")
    return claims
