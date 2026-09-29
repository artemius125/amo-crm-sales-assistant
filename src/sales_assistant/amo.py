"""Официальные вебхуки amoCRM и публикация внутреннего примечания."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs

import httpx

from .config import Settings
from .suggestions import Suggestion

FORM_FIELD = re.compile(r"^message\[add\]\[(\d+)\]\[(\w+)\]$")


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    text: str
    talk_id: str
    lead_id: int | None
    account_id: str


def parse_incoming(content_type: str, body: bytes) -> list[IncomingMessage]:
    if len(body) > 1_000_000:
        raise ValueError("Слишком большой вебхук")
    if "application/json" in content_type:
        import json
        payload = json.loads(body)
        records = payload.get("message", {}).get("add", [])
        account = payload.get("account", {})
        account_id = str(account.get("id", "")) if isinstance(account, dict) else ""
    elif "application/x-www-form-urlencoded" in content_type:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        grouped: dict[int, dict[str, str]] = {}
        for key, values in fields.items():
            match = FORM_FIELD.match(key)
            if match and values:
                grouped.setdefault(int(match.group(1)), {})[match.group(2)] = values[0]
        records = list(grouped.values())
        account_id = fields.get("account[id]", [""])[0]
    else:
        raise ValueError("Неподдерживаемый Content-Type вебхука")
    result: list[IncomingMessage] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        message_id = str(record.get("id", "")).strip()
        text = str(record.get("text", "")).strip()
        author = record.get("author", {})
        author_type = author.get("type", "external") if isinstance(author, dict) else "external"
        if not message_id or not text or author_type != "external":
            continue
        element_type = str(record.get("element_type", ""))
        raw_lead = str(record.get("element_id", ""))
        lead_id = int(raw_lead) if raw_lead.isdigit() and element_type in ("", "1", "lead") else None
        result.append(IncomingMessage(
            id=message_id, text=text[:5000], talk_id=str(record.get("talk_id", "")),
            lead_id=lead_id, account_id=account_id,
        ))
    return result


def publish_note(settings: Settings, lead_id: int, suggestion: Suggestion) -> int:
    if not settings.amo_domain or not settings.amo_token:
        raise ValueError("Для записи примечания нужны AMO_DOMAIN и AMO_TOKEN")
    evidence = ", ".join(item.id for item in suggestion.evidence) or "нет подтверждённых фактов"
    tip_evidence = ", ".join(item.id for item in suggestion.manager_evidence) or "нет"
    note_text = (
        "Помощник менеджера · черновик\n\n"
        f"Ответ клиенту:\n{suggestion.customer_reply}\n\n"
        f"Подсказка менеджеру:\n{suggestion.manager_tip}\n\n"
        f"Основания ответа: {evidence}\nОснования подсказки: {tip_evidence}\n"
        f"Режим: {suggestion.mode}. Проверьте перед отправкой."
    )
    url = f"https://{settings.amo_domain}/api/v4/leads/{lead_id}/notes"
    response = httpx.post(
        url, json=[{"note_type": "common", "params": {"text": note_text}}],
        headers={"Authorization": f"Bearer {settings.amo_token}"}, timeout=15,
    )
    response.raise_for_status()
    notes = response.json().get("_embedded", {}).get("notes", [])
    if not notes or not isinstance(notes[0].get("id"), int):
        raise ValueError("amoCRM не вернула ID примечания")
    return notes[0]["id"]
