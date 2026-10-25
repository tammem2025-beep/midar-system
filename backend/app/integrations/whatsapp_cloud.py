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
