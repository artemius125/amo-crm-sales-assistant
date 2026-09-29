"""Fallback for the demo account when amoCRM cannot deliver its webhook.

The events list is public API; text is read from amoCRM's browser timeline endpoint.
That second endpoint is undocumented and should be replaced by a working webhook.
"""

from __future__ import annotations

import httpx

from .amo import IncomingMessage
from .config import Settings


def recent_events(settings: Settings, since: int) -> list[dict]:
    base = f"https://{settings.amo_domain}"
    response = httpx.get(
        base + "/api/v4/events",
        params={"filter[type]": "incoming_chat_message",
                "filter[created_at][from]": since, "limit": 100},
        headers={"Authorization": f"Bearer {settings.amo_token}"}, timeout=15,
    )
    response.raise_for_status()
    return response.json().get("_embedded", {}).get("events", [])


def message_from_event(settings: Settings, event: dict) -> IncomingMessage | None:
    message = (event.get("value_after") or [{}])[0].get("message") or {}
    message_id = str(message.get("id", ""))
    lead_id = event.get("entity_id") if event.get("entity_type") == "lead" else None
    if not message_id or not isinstance(lead_id, int):
        return None
    response = httpx.get(
        f"https://{settings.amo_domain}/ajax/v3/leads/{lead_id}/events_timeline",
        headers={"Authorization": f"Bearer {settings.amo_token}"}, timeout=15,
    )
    response.raise_for_status()
    for row in response.json().get("_embedded", {}).get("items", []):
        data = row.get("data") or {}
        if str(data.get("id", "")) == message_id:
            text = (data.get("message") or {}).get("text", "").strip()
            if text:
                return IncomingMessage(message_id, text[:5000],
                                       str(message.get("talk_id", "")), lead_id,
                                       settings.amo_account_id)
    return None
