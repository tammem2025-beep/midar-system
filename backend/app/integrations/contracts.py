"""Stable contract for provider adapters.

A provider is not considered available merely because it appears in the UI catalog.
Only implementations registered here can perform external work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    account_authorization: bool = False
    verify_destination: bool = False
    publish_text: bool = False
    publish_media: bool = False
    analytics: bool = False
    inbox: bool = False
    inbound_webhooks: bool = False


class ProviderConnector(Protocol):
    """Minimal capability-driven contract for provider-specific adapters."""

    platform: str
    capabilities: ProviderCapabilities

    async def verify_destination(self, token: str, target: str) -> dict[str, Any]: ...

    async def publish_text(self, token: str, target: str, text: str) -> dict[str, Any]: ...


VerifyDestinationFn = Callable[[str, str], Awaitable[dict[str, Any]]]
PublishTextFn = Callable[[str, str, str], Awaitable[dict[str, Any]]]
