"""Server-side OAuth and lightweight publishing adapters for approved social APIs.

Client secrets and tokens stay on the backend. The module does not infer granted
permissions from the requested scopes; it stores the scopes returned by the provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import os
import re
from urllib.parse import urlencode, urlparse

import httpx

TIMEOUT = httpx.Timeout(18.0, connect=6.0)


class SocialOAuthError(RuntimeError):
    """Safe provider error suitable for application logs/UI without credential leakage."""


class SocialDeliveryUnknown(SocialOAuthError):
    """A write request may have reached the provider, but its result is uncertain."""


@dataclass(frozen=True, slots=True)
class SocialOAuthConfig:
    provider: str
    client_id: str
    client_secret: str
    redirect_uri: str
    authorization_endpoint: str
    token_endpoint: str
    scopes: tuple[str, ...]
    pkce: bool


@dataclass(frozen=True, slots=True)
class LinkedSocialIdentity:
    provider: str
    external_id: str
    account_name: str
    handle: str
    access_token: str
    refresh_token: str | None
    token_type: str
    scopes: tuple[str, ...]
    expires_at: object | None


_CONFIG = {
    "x": {
        "client_id": "X_CLIENT_ID",
        "client_secret": "X_CLIENT_SECRET",
        "redirect_uri": "X_REDIRECT_URI",
        "authorization_endpoint": "https://x.com/i/oauth2/authorize",
        "token_endpoint": "https://api.x.com/2/oauth2/token",
        "scopes": ("users.read", "tweet.read", "tweet.write", "offline.access"),
        "pkce": True,
    },
    "linkedin": {
        "client_id": "LINKEDIN_CLIENT_ID",
        "client_secret": "LINKEDIN_CLIENT_SECRET",
        "redirect_uri": "LINKEDIN_REDIRECT_URI",
        "authorization_endpoint": "https://www.linkedin.com/oauth/v2/authorization",
        "token_endpoint": "https://www.linkedin.com/oauth/v2/accessToken",
        "scopes": ("openid", "profile", "email", "w_member_social"),
        "pkce": False,
    },
    "tiktok": {
        "client_id": "TIKTOK_CLIENT_KEY",
        "client_secret": "TIKTOK_CLIENT_SECRET",
        "redirect_uri": "TIKTOK_REDIRECT_URI",
        "authorization_endpoint": "https://www.tiktok.com/v2/auth/authorize/",
        "token_endpoint": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": ("user.info.basic", "video.list"),
        "pkce": True,
    },
    "youtube": {
        "client_id": "YOUTUBE_CLIENT_ID",
        "client_secret": "YOUTUBE_CLIENT_SECRET",
        "redirect_uri": "YOUTUBE_REDIRECT_URI",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "scopes": ("openid", "email", "profile", "https://www.googleapis.com/auth/youtube.readonly"),
        "pkce": True,
    },
}


def _safe_redirect_uri(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment or parsed.query:
        return False
    if os.getenv("APP_ENV", "development").lower() == "production":
        return parsed.scheme == "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    return True


def get_social_oauth_config(provider: str) -> SocialOAuthConfig | None:
    key = (provider or "").strip().casefold()
    definition = _CONFIG.get(key)
    if not definition:
        return None
    client_id = os.getenv(definition["client_id"], "").strip()
    client_secret = os.getenv(definition["client_secret"], "").strip()
    redirect_uri = os.getenv(definition["redirect_uri"], "").strip()
    parsed_redirect = urlparse(redirect_uri)
    if not client_id or not client_secret or not _safe_redirect_uri(redirect_uri):
        return None
    # LinkedIn only accepts registered absolute HTTPS callback URLs.
    if key == "linkedin" and parsed_redirect.scheme != "https":
        return None
    return SocialOAuthConfig(
        provider=key, client_id=client_id, client_secret=client_secret,
        redirect_uri=redirect_uri, authorization_endpoint=definition["authorization_endpoint"],
        token_endpoint=definition["token_endpoint"], scopes=definition["scopes"],
        pkce=bool(definition["pkce"]) and not (key == "tiktok" and urlparse(redirect_uri).scheme == "https"),
    )


def make_social_authorization_url(config: SocialOAuthConfig, state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "state": state,
        "scope": ",".join(config.scopes) if config.provider == "tiktok" else " ".join(config.scopes),
    }
    if config.provider == "tiktok":
        params["client_key"] = config.client_id
    else:
        params["client_id"] = config.client_id
    if config.pkce:
        challenge = code_challenge
        if config.provider == "tiktok":
            padding = "=" * ((4 - len(challenge) % 4) % 4)
            challenge = base64.urlsafe_b64decode(challenge + padding).hex()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    if config.provider == "youtube":
        params.update({"access_type": "offline", "include_granted_scopes": "true", "prompt": "consent"})
    return f"{config.authorization_endpoint}?{urlencode(params)}"


async def _json_response(response: httpx.Response, *, provider: str, operation: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            if operation == "publish":
                raise SocialDeliveryUnknown(f"{provider} publication response was unavailable; check the destination before retrying.") from exc
        raise SocialOAuthError(f"{provider} returned an unreadable response during {operation}.") from exc
    if response.status_code >= 500 and operation == "publish":
        raise SocialDeliveryUnknown(f"{provider} may have accepted the post; verify the destination before retrying.")
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise SocialOAuthError(f"{provider} rejected the {operation} request (HTTP {response.status_code}).")
    if isinstance(payload.get("error"), dict) or (isinstance(payload.get("error"), str) and payload.get("error")):
        raise SocialOAuthError(f"{provider} rejected the {operation} request.")
    return payload


def _scopes(token_payload: dict) -> tuple[str, ...]:
    raw = token_payload.get("scope") or token_payload.get("scopes") or ""
    if isinstance(raw, list):
        values = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        values = [x.strip() for x in re.split(r"[,\s]+", raw) if x.strip()]
    else:
        values = []
    return tuple(dict.fromkeys(values))


async def exchange_and_identify(
    config: SocialOAuthConfig, *, code: str, code_verifier: str, scope_hint: str = "",
) -> LinkedSocialIdentity:
    if not isinstance(code, str) or not code or len(code) > 4096:
        raise SocialOAuthError("The provider authorization code is missing or invalid.")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    auth = None
    if config.provider == "tiktok":
        data.update({"client_key": config.client_id, "client_secret": config.client_secret})
    elif config.provider == "x":
        # X's confidential-client token exchange uses HTTP Basic authentication.
        auth = httpx.BasicAuth(config.client_id, config.client_secret)
    else:
        data.update({"client_id": config.client_id, "client_secret": config.client_secret})
    if config.pkce:
        data["code_verifier"] = code_verifier
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                config.token_endpoint, data=data, auth=auth,
                headers={"Accept": "application/json"},
            )
            token_response = await _json_response(response, provider=config.provider, operation="token exchange")
            if config.provider == "tiktok":
                token_payload = token_response.get("data") if isinstance(token_response.get("data"), dict) else token_response
                if token_response.get("message") not in {None, "success"} or token_payload.get("error_code") not in {None, 0}:
                    raise SocialOAuthError("TikTok rejected authorization; confirm Login Kit and requested scopes are approved.")
            else:
                token_payload = token_response
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token or len(access_token) > 16384:
                raise SocialOAuthError(f"{config.provider} did not return a usable access token.")
            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
            if config.provider == "x":
                profile_response = await client.get("https://api.x.com/2/users/me", params={"user.fields": "id,name,username,profile_image_url"}, headers=headers)
                profile_payload = await _json_response(profile_response, provider="X", operation="profile lookup")
                profile = profile_payload.get("data") if isinstance(profile_payload.get("data"), dict) else {}
                external_id = str(profile.get("id") or "")
                username = str(profile.get("username") or "")
                account_name = str(profile.get("name") or username or "X account")
                handle = f"@{username}" if username else f"x:{external_id}"
            elif config.provider == "linkedin":
                profile_response = await client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
                profile_payload = await _json_response(profile_response, provider="LinkedIn", operation="profile lookup")
                external_id = str(profile_payload.get("sub") or "")
                account_name = str(profile_payload.get("name") or profile_payload.get("given_name") or "LinkedIn member")
                username = str(profile_payload.get("preferred_username") or "")
                handle = f"@{username}" if username and not "@" in username else f"linkedin:{external_id}"
            elif config.provider == "tiktok":
                profile_response = await client.get(
                    "https://open.tiktokapis.com/v2/user/info/",
                    params={"fields": "open_id,display_name,avatar_url"},
                    headers=headers,
                )
                profile_payload = await _json_response(profile_response, provider="TikTok", operation="profile lookup")
                user = profile_payload.get("data", {}).get("user", {}) if isinstance(profile_payload.get("data"), dict) else {}
                external_id = str(user.get("open_id") or "")
                username = str(user.get("username") or "")
                account_name = str(user.get("display_name") or username or "TikTok account")
                handle = f"@{username}" if username else f"tiktok:{external_id}"
            elif config.provider == "youtube":
                profile_response = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "id,snippet", "mine": "true", "maxResults": 50},
                    headers=headers,
                )
                profile_payload = await _json_response(profile_response, provider="YouTube", operation="channel lookup")
                items = profile_payload.get("items")
                channels = [x for x in items if isinstance(x, dict) and x.get("id")] if isinstance(items, list) else []
                if not channels:
                    raise SocialOAuthError("Google authorized successfully, but no YouTube channel was returned for this account.")
                channel = channels[0]
                snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
                external_id = str(channel["id"])
                account_name = str(snippet.get("title") or "YouTube channel")
                custom_url = str(snippet.get("customUrl") or "")
                handle = custom_url if custom_url.startswith("@") else (f"youtube:{external_id}")
            else:
                raise SocialOAuthError("This provider is not supported by this OAuth module.")
    except SocialOAuthError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise SocialOAuthError(f"Could not complete {config.provider} authorization. Check app configuration and requested permissions.") from exc

    if not external_id or len(external_id) > 180:
        raise SocialOAuthError(f"{config.provider} did not provide a verifiable account identifier.")
    granted_scopes = _scopes(token_payload)
    if not granted_scopes and scope_hint:
        # A few provider versions report the granted scopes only on the OAuth redirect.
        granted_scopes = tuple(x.strip() for x in re.split(r"[,\s]+", scope_hint) if x.strip())
    expires_in = token_payload.get("expires_in")
    expires_at = None
    try:
        if expires_in is not None:
            seconds = int(expires_in)
            if 0 < seconds <= 366 * 24 * 60 * 60:
                from datetime import datetime, timezone
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    except (ValueError, TypeError, OverflowError):
        expires_at = None
    refresh_token = token_payload.get("refresh_token")
    return LinkedSocialIdentity(
        provider=config.provider, external_id=external_id, account_name=account_name[:160],
        handle=handle[:180], access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        token_type=str(token_payload.get("token_type") or "Bearer")[:32],
        scopes=granted_scopes,
        expires_at=expires_at,
    )


async def publish_text(provider: str, access_token: str, external_id: str, text: str) -> dict[str, str]:
    """Publish text only on networks with documented text-post API support."""
    provider = (provider or "").casefold()
    message = (text or "").strip()
    if not message:
        raise SocialOAuthError("Post text cannot be empty.")
    if provider == "x":
        if len(message) > 280:
            raise SocialOAuthError("X post text exceeds 280 characters; shorten the post before publishing.")
        url, headers, payload = (
            "https://api.x.com/2/tweets",
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"},
            {"text": message},
        )
    elif provider == "linkedin":
        if len(message) > 3000:
            raise SocialOAuthError("LinkedIn post text exceeds the supported size.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", external_id):
            raise SocialOAuthError("LinkedIn member identity is invalid.")
        url = "https://api.linkedin.com/rest/posts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Linkedin-Version": os.getenv("LINKEDIN_RESTLI_VERSION", "202610"),
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = {
            "author": f"urn:li:person:{external_id}",
            "commentary": message,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
    else:
        raise SocialOAuthError("Text-only publishing is not implemented for this provider.")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SocialDeliveryUnknown(f"{provider} post result could not be confirmed; check the account before retrying.") from exc
    try:
        body = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            raise SocialDeliveryUnknown(f"{provider} may have accepted the post; verify before retrying.") from exc
        body = {}
    if response.status_code >= 500:
        raise SocialDeliveryUnknown(f"{provider} may have accepted the post; verify before retrying.")
    if response.status_code >= 400 or not isinstance(body, dict) or body.get("errors") or body.get("error"):
        raise SocialOAuthError(f"{provider} rejected the post (HTTP {response.status_code}). Check granted permissions and account eligibility.")
    remote_id = (body.get("data") or {}).get("id") if isinstance(body.get("data"), dict) else None
    if not remote_id:
        remote_id = response.headers.get("x-restli-id")
    if not remote_id:
        raise SocialDeliveryUnknown(f"{provider} did not confirm a post ID; verify the destination before retrying.")
    return {"id": str(remote_id)}


async def fetch_recent_content(
    provider: str, access_token: str, external_id: str, *, scopes: tuple[str, ...], limit: int = 30,
) -> list[dict[str, str | None]]:
    """Fetch real recent feed items only when the connected account granted the needed read scope."""
    provider = (provider or "").casefold()
    bounded_limit = max(1, min(int(limit), 50))
    if provider == "x":
        required = "tweet.read"
        if required not in scopes:
            raise SocialOAuthError("X لم يمنح صلاحية tweet.read لهذا الحساب؛ أعد التفويض بالصلاحية إن كانت متاحة.")
        params = {
            "max_results": str(max(5, min(bounded_limit, 100))),
            "tweet.fields": "id,text,created_at,public_metrics,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "media_key,type,url,preview_image_url,alt_text",
        }
        url = f"https://api.x.com/2/users/{external_id}/tweets"
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
                response = await client.get(url, params=params, headers=headers)
            payload = await _json_response(response, provider="X", operation="feed lookup")
        except SocialOAuthError:
            raise
        except httpx.HTTPError as exc:
            raise SocialOAuthError("تعذر جلب منشورات X من الواجهة الرسمية.") from exc
        includes = payload.get("includes") if isinstance(payload.get("includes"), dict) else {}
        media_by_key = {
            item.get("media_key"): item for item in includes.get("media", [])
            if isinstance(item, dict) and item.get("media_key")
        } if isinstance(includes.get("media"), list) else {}
        items = []
        for item in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            attachments = item.get("attachments") if isinstance(item.get("attachments"), dict) else {}
            keys = attachments.get("media_keys") if isinstance(attachments.get("media_keys"), list) else []
            remote_media = next((media_by_key.get(key) for key in keys if media_by_key.get(key)), {})
            mtype = str(remote_media.get("type") or "TEXT").upper()
            media_url = remote_media.get("url") or remote_media.get("preview_image_url")
            items.append({
                "id": str(item["id"]), "caption": str(item.get("text") or ""),
                "media_type": "VIDEO" if "video" in mtype else "IMAGE" if "photo" in mtype else "TEXT",
                "media_url": media_url if isinstance(media_url, str) else None,
                "thumbnail_url": remote_media.get("preview_image_url") if isinstance(remote_media.get("preview_image_url"), str) else media_url if isinstance(media_url, str) else None,
                "permalink": f"https://x.com/i/web/status/{item['id']}",
                "timestamp": item.get("created_at") if isinstance(item.get("created_at"), str) else None,
                "platform": "X",
            })
        return items[:bounded_limit]

    if provider == "tiktok":
        if "video.list" not in scopes:
            raise SocialOAuthError("TikTok لم يمنح صلاحية video.list لهذا الحساب.")
        fields = "id,title,video_description,create_time,cover_image_url,share_url,video_duration,view_count,like_count,comment_count,share_count"
        url = f"https://open.tiktokapis.com/v2/video/list/?fields={fields}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
                response = await client.post(
                    url, json={"max_count": bounded_limit},
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"},
                )
            payload = await _json_response(response, provider="TikTok", operation="feed lookup")
        except SocialOAuthError:
            raise
        except httpx.HTTPError as exc:
            raise SocialOAuthError("تعذر جلب فيديوهات TikTok من الواجهة الرسمية.") from exc
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        videos = data.get("videos") if isinstance(data.get("videos"), list) else []
        items = []
        for item in videos:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            video_id = str(item["id"])
            cover = item.get("cover_image_url")
            items.append({
                "id": video_id,
                "caption": str(item.get("title") or item.get("video_description") or ""),
                "media_type": "VIDEO",
                "media_url": item.get("share_url") if isinstance(item.get("share_url"), str) else None,
                "thumbnail_url": cover if isinstance(cover, str) else None,
                "permalink": item.get("share_url") if isinstance(item.get("share_url"), str) else f"https://www.tiktok.com/video/{video_id}",
                "timestamp": None,
                "platform": "TikTok",
            })
        return items

    if provider == "youtube":
        required = "https://www.googleapis.com/auth/youtube.readonly"
        if required not in scopes:
            raise SocialOAuthError("YouTube لم يمنح صلاحية youtube.readonly لهذا الحساب.")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
                channel_response = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "contentDetails", "id": external_id},
                    headers=headers,
                )
                channel_payload = await _json_response(channel_response, provider="YouTube", operation="channel lookup")
                channels = channel_payload.get("items")
                channel = channels[0] if isinstance(channels, list) and channels and isinstance(channels[0], dict) else {}
                content_details = channel.get("contentDetails") if isinstance(channel.get("contentDetails"), dict) else {}
                related = content_details.get("relatedPlaylists") if isinstance(content_details.get("relatedPlaylists"), dict) else {}
                uploads_id = related.get("uploads")
                if not uploads_id:
                    return []
                playlist_response = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    params={"part": "snippet,contentDetails", "playlistId": str(uploads_id), "maxResults": bounded_limit},
                    headers=headers,
                )
                playlist_payload = await _json_response(playlist_response, provider="YouTube", operation="playlist lookup")
                playlist_items = playlist_payload.get("items") if isinstance(playlist_payload.get("items"), list) else []
                video_ids = []
                snippets = {}
                for row in playlist_items:
                    if not isinstance(row, dict):
                        continue
                    details = row.get("contentDetails") if isinstance(row.get("contentDetails"), dict) else {}
                    snippet = row.get("snippet") if isinstance(row.get("snippet"), dict) else {}
                    resource = snippet.get("resourceId") if isinstance(snippet.get("resourceId"), dict) else {}
                    video_id = str(details.get("videoId") or resource.get("videoId") or "")
                    if video_id:
                        video_ids.append(video_id)
                        snippets[video_id] = snippet
                video_payload = {}
                if video_ids:
                    video_response = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "snippet,contentDetails,statistics", "id": ",".join(video_ids)},
                        headers=headers,
                    )
                    video_payload = await _json_response(video_response, provider="YouTube", operation="video lookup")
        except SocialOAuthError:
            raise
        except httpx.HTTPError as exc:
            raise SocialOAuthError("تعذر جلب فيديوهات YouTube من الواجهة الرسمية.") from exc
        items = []
        for item in video_payload.get("items", []) if isinstance(video_payload.get("items"), list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else snippets.get(str(item["id"]), {})
            thumbs = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
            thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {})
            thumb_url = thumb.get("url") if isinstance(thumb, dict) else None
            video_id = str(item["id"])
            items.append({
                "id": video_id, "caption": str(snippet.get("title") or ""),
                "media_type": "VIDEO",
                "media_url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": thumb_url if isinstance(thumb_url, str) else None,
                "permalink": f"https://www.youtube.com/watch?v={video_id}",
                "timestamp": snippet.get("publishedAt") if isinstance(snippet.get("publishedAt"), str) else None,
                "platform": "YouTube",
            })
        items.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
        return items[:bounded_limit]

    raise SocialOAuthError("قراءة المحتوى غير منفذة لهذه المنصة في هذا الإصدار.")


@dataclass(frozen=True, slots=True)
class RefreshedProviderToken:
    access_token: str
    refresh_token: str | None
    token_type: str
    scopes: tuple[str, ...]
    expires_at: datetime | None


async def refresh_provider_access_token(
    config: SocialOAuthConfig, refresh_token: str,
) -> RefreshedProviderToken:
    """Refresh supported OAuth access tokens; callers persist new ciphertext before reuse."""
    if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 16384:
        raise SocialOAuthError(f"{config.provider} refresh token is missing or invalid.")
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    auth = None
    if config.provider == "x":
        # X confidential clients authenticate with HTTP Basic; public-client
        # integrations use a client_id form value instead.
        auth = httpx.BasicAuth(config.client_id, config.client_secret)
    elif config.provider == "tiktok":
        data.update({"client_key": config.client_id, "client_secret": config.client_secret})
    else:
        data.update({"client_id": config.client_id, "client_secret": config.client_secret})
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                config.token_endpoint, data=data, auth=auth,
                headers={"Accept": "application/json"},
            )
        response_payload = await _json_response(response, provider=config.provider, operation="token refresh")
    except SocialOAuthError:
        raise
    except httpx.HTTPError as exc:
        raise SocialOAuthError(f"Could not refresh the {config.provider} access token.") from exc

    if config.provider == "tiktok":
        payload = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else response_payload
        if response_payload.get("message") not in {None, "success"} or payload.get("error_code") not in {None, 0}:
            raise SocialOAuthError("TikTok rejected token refresh; reconnect the account if the grant has expired.")
    else:
        payload = response_payload
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 16384:
        raise SocialOAuthError(f"{config.provider} did not return a usable refreshed access token.")

    seconds = payload.get("expires_in")
    expires_at = None
    try:
        ttl = int(seconds)
        if 0 < ttl <= 366 * 24 * 60 * 60:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    except (ValueError, TypeError, OverflowError):
        pass
    token_scope = _scopes(payload)
    new_refresh_token = payload.get("refresh_token")
    return RefreshedProviderToken(
        access_token=access_token,
        refresh_token=new_refresh_token if isinstance(new_refresh_token, str) and new_refresh_token else refresh_token,
        token_type=str(payload.get("token_type") or "Bearer")[:32],
        scopes=token_scope,
        expires_at=expires_at,
    )
