"""WhatsApp Business Cloud API helpers for M."""
from __future__ import annotations
import os
import re
import httpx

GRAPH_ROOT = "https://graph.facebook.com"


class WhatsAppCloudError(RuntimeError):
    pass


class WhatsAppDeliveryUnknown(RuntimeError):
    pass


def get_whatsapp_config():
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    version = os.getenv("WHATSAPP_GRAPH_API_VERSION", os.getenv("META_GRAPH_API_VERSION", "v26.0")).strip()
    if not phone_id or not access_token or not re.fullmatch(r"[0-9]{1,32}", phone_id):
        return None
    if not re.fullmatch(r"v[0-9]{1,2}\.0", version):
        return None
    return {"phone_number_id": phone_id, "access_token": access_token, "graph_version": version}


async def verify_business_number(config):
    async with httpx.AsyncClient(timeout=httpx.Timeout(18.0, connect=6.0), follow_redirects=False) as client:
        response = await client.get(
            f"{GRAPH_ROOT}/{config['graph_version']}/{config['phone_number_id']}",
            params={"fields": "id,display_phone_number,verified_name,quality_rating"},
            headers={"Authorization": f"Bearer {config['access_token']}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise WhatsAppCloudError("WhatsApp Cloud API could not verify the configured business number.")
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("id") or "") != config["phone_number_id"]:
        raise WhatsAppCloudError("WhatsApp returned an unexpected phone-number identity.")
    return {
        "id": str(payload["id"]),
        "display_phone_number": payload.get("display_phone_number"),
        "verified_name": payload.get("verified_name"),
        "quality_rating": payload.get("quality_rating"),
    }


def get_webhook_secrets():
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    app_secret = os.getenv("WHATSAPP_APP_SECRET", os.getenv("META_APP_SECRET", "")).strip()
    if not verify_token or not app_secret:
        return None
    return verify_token, app_secret


def verify_webhook_signature(raw_body: bytes, supplied: str, app_secret: str) -> bool:
    import hmac
    import hashlib
    if not raw_body or len(raw_body) > 2 * 1024 * 1024:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (supplied or "").strip())


async def send_text(*, graph_version: str, phone_number_id: str, access_token: str, recipient: str, text: str):
    import re
    import httpx
    to = (recipient or "").strip().lstrip("+")
    body = (text or "").strip()
    if not re.fullmatch(r"[0-9]{7,20}", to):
        raise WhatsAppCloudError("Recipient phone number must use international digits-only format.")
    if not body or len(body) > 4096:
        raise WhatsAppCloudError("Message text must contain 1 to 4096 characters.")
    if not access_token or not re.fullmatch(r"[0-9]{1,32}", phone_number_id):
        raise WhatsAppCloudError("WhatsApp Business credentials are missing or invalid.")
    url = f"{GRAPH_ROOT}/{graph_version}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18.0, connect=6.0), follow_redirects=False) as client:
            response = await client.post(
                url,
                json={"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                      "type": "text", "text": {"preview_url": False, "body": body}},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"},
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise WhatsAppDeliveryUnknown("WhatsApp delivery could not be confirmed; check the conversation before retrying.") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            raise WhatsAppDeliveryUnknown("WhatsApp may have accepted the message; verify before retrying.") from exc
        raise WhatsAppCloudError("WhatsApp returned an unreadable response.") from exc
    if response.status_code >= 500:
        raise WhatsAppDeliveryUnknown("WhatsApp may have accepted the message; verify before retrying.")
    if response.status_code >= 400 or not isinstance(payload, dict) or payload.get("error"):
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error, dict) else response.status_code
        raise WhatsAppCloudError(f"WhatsApp rejected the message (API code {str(code)[:24]}).")
    messages = payload.get("messages")
    message = messages[0] if isinstance(messages, list) and messages and isinstance(messages[0], dict) else {}
    message_id = message.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise WhatsAppDeliveryUnknown("WhatsApp did not confirm the message ID; verify before retrying.")
    contacts = payload.get("contacts")
    contact = contacts[0] if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict) else {}
    return {"message_id": message_id, "recipient_id": str(contact.get("wa_id") or to)}
