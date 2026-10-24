"""Runtime registry of implemented providers, distinct from the public roadmap catalog."""
from __future__ import annotations

from typing import Any

from .contracts import ProviderCapabilities, ProviderConnector, PublishTextFn, VerifyDestinationFn


class ProviderNotImplementedError(RuntimeError):
    """Raised when code requests an external provider with no live adapter."""


class TelegramConnector:
    """Adapter around the currently implemented Telegram destination/text operations.

    Functions are injectable so API tests can stub remote calls without network access.
    This adapter intentionally makes no claim about OAuth, media, analytics, inbox, or webhooks.
    """

    platform = "Telegram"
    capabilities = ProviderCapabilities(
        account_authorization=False,
        verify_destination=True,
        publish_text=True,
        publish_media=False,
        analytics=False,
        inbox=False,
        inbound_webhooks=False,
    )

    def __init__(self, verify_fn: VerifyDestinationFn, publish_fn: PublishTextFn) -> None:
        self._verify_fn = verify_fn
        self._publish_fn = publish_fn

    async def verify_destination(self, token: str, target: str) -> dict[str, Any]:
        return await self._verify_fn(token, target)

    async def publish_text(self, token: str, target: str, text: str) -> dict[str, Any]:
        return await self._publish_fn(token, target, text)


def get_connector(
    platform: str,
    *,
    telegram_verify_fn: VerifyDestinationFn,
    telegram_publish_fn: PublishTextFn,
) -> ProviderConnector | None:
    """Return an adapter only for currently implemented external capabilities.

    The catalog is intentionally not used as the runtime registry. Planned providers
    must never accidentally become callable merely because a catalog entry exists.
    """
    normalized = (platform or "").strip().casefold()
    if normalized == "telegram":
        return TelegramConnector(telegram_verify_fn, telegram_publish_fn)
    return None
