"""Meta Graph API helpers for server-side, read-only social account connections."""
from __future__ import annotations
import os
import re
from urllib.parse import urlencode, urlparse
import httpx

META_AUTH_ENDPOINT = "https://www.facebook.com/{version}/dialog/oauth"
META_GRAPH_ROOT = "https://graph.facebook.com"
META_SCOPES = ("pages_show_list", "pages_read_engagement", "pages_read_user_content", "instagram_basic")

class MetaGraphError(RuntimeError):
    """Safe provider failure that never includes tokens or raw provider responses."""

def get_meta_config() -> dict[str, str] | None:
    app_id = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()
    redirect_uri = os.getenv("META_REDIRECT_URI", "").strip()
    version = os.getenv("META_GRAPH_API_VERSION", "v26.0").strip()
    if not (app_id and app_secret and redirect_uri) or not re.fullmatch(r"v[0-9]{1,2}\.0", version):
        return None
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment:
        return None
    if os.getenv("APP_ENV", "development").lower() == "production":
        if parsed.scheme != "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return None
    elif parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return {"app_id": app_id, "app_secret": app_secret, "redirect_uri": redirect_uri, "version": version}

def make_meta_authorization_url(config: dict[str, str], state: str) -> str:
    params = {
        "client_id": config["app_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": ",".join(META_SCOPES), "state": state,
    }
    return f"{META_AUTH_ENDPOINT.format(version=config['version'])}?{urlencode(params)}"

def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if code is not None:
            return f"Meta rejected the request (error code {str(code)[:24]}). Check app status, account eligibility, and permissions."
    except (ValueError, TypeError):
        pass
    return "Meta could not complete the operation. Check the app configuration and permissions."

async def _get_json(url: str, params: dict[str, str | int] | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18.0, connect=6.0), follow_redirects=False) as client:
            response = await client.get(url, params=params, headers={"Accept": "application/json"})
        payload = response.json()
        if response.status_code >= 400 or not isinstance(payload, dict) or payload.get("error"):
            raise MetaGraphError(_error_message(response))
        return payload
    except MetaGraphError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise MetaGraphError("Could not reach Meta Graph API. Check the network and retry.") from exc

async def exchange_meta_code(config: dict[str, str], code: str) -> dict:
    if not code or len(code) > 4096:
        raise MetaGraphError("Meta authorization code is invalid.")
    payload = await _get_json(f"{META_GRAPH_ROOT}/{config['version']}/oauth/access_token", {
        "client_id": config["app_id"], "client_secret": config["app_secret"],
        "redirect_uri": config["redirect_uri"], "code": code,
    })
    if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        raise MetaGraphError("Meta did not return a valid access token.")
    return payload

async def exchange_for_long_lived_token(config: dict[str, str], short_lived_token: str) -> dict:
    payload = await _get_json(f"{META_GRAPH_ROOT}/{config['version']}/oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": config["app_id"],
        "client_secret": config["app_secret"], "fb_exchange_token": short_lived_token,
    })
    if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        raise MetaGraphError("Meta did not return a long-lived user token.")
    return payload

async def list_managed_pages(config: dict[str, str], user_token: str) -> list[dict]:
    payload = await _get_json(f"{META_GRAPH_ROOT}/{config['version']}/me/accounts", {
        "access_token": user_token,
        "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 100,
    })
    pages = payload.get("data")
    if not isinstance(pages, list):
        raise MetaGraphError("Meta returned an unexpected managed Pages response.")
    return [item for item in pages if isinstance(item, dict) and item.get("id") and item.get("name") and item.get("access_token")]

async def _graph_edge(config: dict[str, str], account_id: str, edge: str, token: str, fields: str, limit: int) -> list[dict]:
    payload = await _get_json(f"{META_GRAPH_ROOT}/{config['version']}/{account_id}/{edge}", {
        "access_token": token, "fields": fields, "limit": max(1, min(int(limit), 50)),
    })
    values = payload.get("data")
    if not isinstance(values, list):
        raise MetaGraphError("Meta returned an unexpected media response.")
    return [item for item in values if isinstance(item, dict)]

def _normalize_instagram(item: dict) -> dict:
    product = str(item.get("media_product_type") or "").upper()
    kind = str(item.get("media_type") or "UNKNOWN").upper()
    children = item.get("children") if isinstance(item.get("children"), dict) else {}
    first_child = next((child for child in children.get("data", []) if isinstance(child, dict)), {})
    media_url = item.get("media_url") or first_child.get("media_url")
    thumbnail = item.get("thumbnail_url") or first_child.get("thumbnail_url") or first_child.get("media_url")
    return {
        "id": str(item.get("id") or ""), "caption": str(item.get("caption") or ""),
        "media_type": "REELS" if product == "REELS" else kind,
        "media_url": media_url if isinstance(media_url, str) else None,
        "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
        "permalink": item.get("permalink") if isinstance(item.get("permalink"), str) else None,
        "timestamp": item.get("timestamp") if isinstance(item.get("timestamp"), str) else None,
        "platform": "Instagram",
    }

async def fetch_account_media(config: dict[str, str], platform: str, account_id: str, token: str, limit: int = 30) -> list[dict]:
    if platform == "Instagram":
        raw = await _graph_edge(config, account_id, "media", token,
            "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,children{media_type,media_url,thumbnail_url}", limit)
        items = [_normalize_instagram(item) for item in raw]
    elif platform == "Facebook":
        raw_posts = await _graph_edge(config, account_id, "posts", token,
            "id,message,created_time,permalink_url,full_picture,attachments{media_type,target,url,title,media}", limit)
        raw_videos = await _graph_edge(config, account_id, "videos", token,
            "id,title,description,created_time,permalink_url,source,picture", limit)
        items = []
        for item in raw_posts:
            attachments = item.get("attachments") if isinstance(item.get("attachments"), dict) else {}
            att_list = attachments.get("data") if isinstance(attachments.get("data"), list) else []
            att = next((entry for entry in att_list if isinstance(entry, dict)), {})
            att_type = str(att.get("media_type") or att.get("type") or "").upper()
            media = att.get("media") if isinstance(att.get("media"), dict) else {}
            image = media.get("image") if isinstance(media.get("image"), dict) else {}
            items.append({
                "id": str(item.get("id") or ""), "caption": str(item.get("message") or att.get("title") or ""),
                "media_type": "VIDEO" if "VIDEO" in att_type else ("IMAGE" if item.get("full_picture") or image.get("src") else "TEXT"),
                "media_url": None, "thumbnail_url": item.get("full_picture") or image.get("src"),
                "permalink": item.get("permalink_url") if isinstance(item.get("permalink_url"), str) else None,
                "timestamp": item.get("created_time") if isinstance(item.get("created_time"), str) else None,
                "platform": "Facebook",
            })
        for item in raw_videos:
            items.append({
                "id": str(item.get("id") or ""), "caption": str(item.get("title") or item.get("description") or ""),
                "media_type": "VIDEO", "media_url": item.get("source") if isinstance(item.get("source"), str) else None,
                "thumbnail_url": item.get("picture") if isinstance(item.get("picture"), str) else None,
                "permalink": item.get("permalink_url") if isinstance(item.get("permalink_url"), str) else None,
                "timestamp": item.get("created_time") if isinstance(item.get("created_time"), str) else None,
                "platform": "Facebook",
            })
    else:
        raise MetaGraphError("Only Facebook Pages and linked Instagram Professional accounts are supported.")
    deduped = {item["id"]: item for item in items if item.get("id")}
    return sorted(deduped.values(), key=lambda item: item.get("timestamp") or "", reverse=True)[:max(1, min(int(limit), 50))]
