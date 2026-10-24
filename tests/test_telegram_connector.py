"""Unit tests for Telegram Bot API request formatting and ambiguous failures."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
import pytest
from app.integrations import telegram


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeAsyncClient:
    queue = []
    calls = []
    error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        type(self).calls.append({"url": url, "json": json})
        if type(self).error is not None:
            raise type(self).error
        return type(self).queue.pop(0)


def setup_fake(monkeypatch, responses):
    FakeAsyncClient.queue = list(responses)
    FakeAsyncClient.calls = []
    FakeAsyncClient.error = None
    monkeypatch.setattr(telegram.httpx, "AsyncClient", FakeAsyncClient)


@pytest.mark.asyncio
async def test_send_text_uses_chat_id_and_plain_text_only(monkeypatch):
    setup_fake(monkeypatch, [FakeResponse({"ok": True, "result": {
        "message_id": 55, "date": 123, "chat": {"id": -100123, "type": "channel"}
    }})])
    result = await telegram.send_text("12345:secret_test_token", "-100123", "مرحبا <script>")
    assert result["message_id"] == 55
    assert FakeAsyncClient.calls[0]["json"] == {"chat_id": "-100123", "text": "مرحبا <script>"}
    assert "parse_mode" not in FakeAsyncClient.calls[0]["json"]
    assert "secret_test_token" not in str(result)


@pytest.mark.asyncio
async def test_channel_verification_requires_admin_and_post_permission(monkeypatch):
    setup_fake(monkeypatch, [
        FakeResponse({"ok": True, "result": {"id": 42, "is_bot": True, "username": "midar_bot"}}),
        FakeResponse({"ok": True, "result": {"id": -100123, "type": "channel", "title": "Test", "username": "test_channel"}}),
        FakeResponse({"ok": True, "result": {"status": "administrator", "can_post_messages": True}}),
    ])
    result = await telegram.verify_channel("12345:secret_test_token", "@test_channel")
    assert result["chat"]["id"] == -100123
    assert [c["url"].rsplit("/", 1)[-1] for c in FakeAsyncClient.calls] == ["getMe", "getChat", "getChatMember"]
    assert FakeAsyncClient.calls[2]["json"] == {"chat_id": -100123, "user_id": 42}


@pytest.mark.asyncio
async def test_ambiguous_transport_failure_is_not_reported_as_definite_rejection(monkeypatch):
    setup_fake(monkeypatch, [])
    req = httpx.Request("POST", "https://api.telegram.org/bot12345:token/sendMessage")
    FakeAsyncClient.error = httpx.ReadTimeout("network timeout", request=req)
    with pytest.raises(telegram.TelegramDeliveryUnknown):
        await telegram.send_text("12345:token", "-100123", "hello")


@pytest.mark.asyncio
async def test_provider_rejection_is_definitive(monkeypatch):
    setup_fake(monkeypatch, [FakeResponse({"ok": False, "error_code": 400, "description": "chat not found"}, status_code=400)])
    with pytest.raises(telegram.TelegramAPIError) as error:
        await telegram.send_text("12345:token", "-100123", "hello")
    assert error.value.error_code == 400
    assert "chat not found" in str(error.value)
