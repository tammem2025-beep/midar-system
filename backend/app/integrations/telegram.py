"""Minimal, explicit Telegram Bot API connector for channel text publishing.

The bot token must be supplied from the server environment. It is never accepted
from API request bodies or returned to clients. This module intentionally only
supports verifying a channel and sending a text message; it does not pretend to
support inbound updates, media posts, or arbitrary Telegram user accounts.
"""
from __future__ import annotations

from typing import Any

import httpx

API_ROOT = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class TelegramAPIError(RuntimeError):
    """Telegram returned a definitive API error (the requested action was rejected)."""

    def __init__(self, message: str, *, error_code: int | None = None):
        super().__init__(message[:500])
        self.error_code = error_code


class TelegramDeliveryUnknown(RuntimeError):
    """The request outcome could not be established; do not automatically resend."""


def _require_token(token: str | None) -> str:
    value = (token or "").strip()
    if not value:
        raise TelegramAPIError("TELEGRAM_BOT_TOKEN is not configured")
    if len(value) > 512 or "/" in value or "\\" in value:
        # Guard against accidental URL construction/injection from a bad env value.
        raise TelegramAPIError("TELEGRAM_BOT_TOKEN has an invalid format")
    return value


async def _call(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _require_token(token)
    url = f"{API_ROOT}/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post(url, json=payload or {})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        # For sendMessage, a transport failure can happen after Telegram accepted
        # a request. Callers must mark the outcome unknown instead of retrying.
        raise TelegramDeliveryUnknown("Telegram request outcome could not be confirmed") from exc

    try:
        data = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            raise TelegramDeliveryUnknown("Telegram returned an unreadable server response") from exc
        raise TelegramAPIError("Telegram returned an invalid response", error_code=response.status_code) from exc

    if response.status_code >= 500:
        raise TelegramDeliveryUnknown("Telegram returned a server error; delivery may be uncertain")
    if response.status_code >= 400 or not isinstance(data, dict) or data.get("ok") is not True:
        description = data.get("description", "request rejected") if isinstance(data, dict) else "request rejected"
        error_code = data.get("error_code", response.status_code) if isinstance(data, dict) else response.status_code
        # Telegram descriptions do not contain the bot token. Keep them short.
        raise TelegramAPIError(f"Telegram rejected the request: {str(description)[:350]}", error_code=error_code)
    result = data.get("result")
    if not isinstance(result, dict):
        raise TelegramAPIError("Telegram returned no result object")
    return result


async def get_bot_info(token: str) -> dict[str, Any]:
    """Verify the bot token with getMe and return safe bot identity fields."""
    result = await _call(token, "getMe")
    return {key: result.get(key) for key in ("id", "is_bot", "first_name", "username") if key in result}


async def verify_channel(token: str, target: str) -> dict[str, Any]:
    """Verify destination exists and the bot has permission to publish to it."""
    token = _require_token(token)
    bot = await get_bot_info(token)
    chat = await _call(token, "getChat", {"chat_id": target})
    if chat.get("type") not in {"channel", "supergroup"}:
        raise TelegramAPIError("قناة النشر يجب أن تكون قناة أو مجموعة فائقة على Telegram")
    member = await _call(token, "getChatMember", {"chat_id": chat.get("id"), "user_id": bot.get("id")})
    role = member.get("status")
    if role not in {"administrator", "creator"}:
        raise TelegramAPIError("يجب إضافة البوت المُهيأ على الخادم إلى القناة كمسؤول قبل النشر")
    if chat.get("type") == "channel" and role == "administrator" and member.get("can_post_messages") is False:
        raise TelegramAPIError("البوت مسؤول في القناة لكنه لا يملك صلاحية نشر الرسائل")
    return {
        "bot": bot,
        "chat": {key: chat.get(key) for key in ("id", "type", "title", "username") if key in chat},
    }


async def send_text(token: str, target_chat_id: str, text: str) -> dict[str, Any]:
    """Send one plain-text message. No parse_mode is used to avoid markup injection."""
    message = (text or "").strip()
    if not message:
        raise TelegramAPIError("لا يمكن نشر رسالة فارغة")
    if len(message) > 4096:
        raise TelegramAPIError("يتجاوز النص حد Telegram البالغ 4096 حرفًا")
    result = await _call(token, "sendMessage", {"chat_id": target_chat_id, "text": message})
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    return {
        "message_id": result.get("message_id"),
        "date": result.get("date"),
        "chat_id": chat.get("id"),
        "chat_type": chat.get("type"),
    }
