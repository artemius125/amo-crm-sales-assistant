"""HTTP API: входящий вебхук, очередь подсказок и локальное демо."""

from __future__ import annotations

import secrets
import asyncio
import logging
import time
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .amo import IncomingMessage, parse_incoming, publish_note
from .poller import recent_events, message_from_event
from .config import Settings
from .store import MessageStore
from .suggestions import SuggestionEngine


class SuggestRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=100)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = SuggestionEngine(settings)
    store = MessageStore(settings.database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(poll_loop()) if settings.amo_polling else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="amoCRM Sales Assistant", version="0.3.0", lifespan=lifespan)

    def manager_access(request: Request, authorization: str | None) -> None:
        # Локальная панель доступна владельцу компьютера без ввода API-ключа.
        # Сетевые клиенты обязаны предъявить ключ, если сервер опубликован наружу.
        if request.client and request.client.host in ("127.0.0.1", "::1", "testclient"):
            return
        if not settings.app_api_key:
            raise HTTPException(status_code=403, detail="Для удалённого доступа задайте APP_API_KEY")
        supplied = (authorization or "").removeprefix("Bearer ")
        if not secrets.compare_digest(supplied, settings.app_api_key):
            raise HTTPException(status_code=401, detail="Неверный APP_API_KEY")

    def process_incoming(item: IncomingMessage) -> None:
        try:
            store.update(item.id, status="processing")
            history = store.previous_messages(item.talk_id, item.id)
            suggestion = engine.suggest(item.text, previous_messages=history)
            payload = suggestion.to_dict()
            store.update(item.id, status="ready", suggestion=payload)
            if settings.publish_notes and item.lead_id:
                note_id = publish_note(settings, item.lead_id, suggestion)
                store.update(item.id, status="published", note_id=note_id)
        except Exception as exc:
            store.update(item.id, status="needs_attention", error=f"{type(exc).__name__}: {exc}")

    async def poll_loop() -> None:
        since = int(time.time()) - 7200
        while True:
            try:
                events = await asyncio.to_thread(recent_events, settings, since)
                for event in reversed(events):
                    message_id = str(((event.get("value_after") or [{}])[0].get("message") or {}).get("id", ""))
                    if not message_id or store.get(message_id):
                        continue
                    item = await asyncio.to_thread(message_from_event, settings, event)
                    if item and store.insert(item.id, item.lead_id, item.talk_id, item.text):
                        await asyncio.to_thread(process_incoming, item)
                if events:
                    since = max(since, max(int(event.get("created_at", 0)) for event in events) - 300)
            except Exception:
                logging.exception("amoCRM polling failed")
            await asyncio.sleep(3)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "documents": len(engine.index.documents),
                "crm_configured": bool(settings.amo_domain and settings.amo_token),
                "crm_polling": settings.amo_polling,
                "llm_configured": bool(settings.llm_api_key),
                "knowledge_database": str(settings.knowledge_db_path)}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        html = (Path(__file__).with_name("web") / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/client", response_class=HTMLResponse)
    def client_chat() -> HTMLResponse:
        if not settings.amo_widget_id or not settings.amo_widget_hash:
            raise HTTPException(status_code=503, detail="Укажите AMO_WIDGET_ID и AMO_WIDGET_HASH")
        html = (Path(__file__).with_name("web") / "client.html").read_text(encoding="utf-8")
        html = html.replace("__AMO_WIDGET_ID__", json.dumps(settings.amo_widget_id))
        html = html.replace("__AMO_WIDGET_HASH__", json.dumps(settings.amo_widget_hash))
        return HTMLResponse(html)

    @app.post("/api/suggest")
    def suggest(payload: SuggestRequest, request: Request,
                authorization: str | None = Header(default=None)) -> dict[str, object]:
        manager_access(request, authorization)
        history = store.recent_messages(payload.conversation_id or "")
        return engine.suggest(payload.message, previous_messages=history).to_dict()

    @app.get("/api/knowledge")
    def knowledge(request: Request, authorization: str | None = Header(default=None)
                  ) -> dict[str, list[dict[str, object]]]:
        manager_access(request, authorization)
        return engine.index.snapshot()

    @app.get("/api/inbox")
    def inbox(request: Request, authorization: str | None = Header(default=None)) -> list[dict]:
        manager_access(request, authorization)
        return store.list_latest()

    @app.get("/api/inbox/{message_id}")
    def inbox_item(message_id: str, request: Request,
                   authorization: str | None = Header(default=None)) -> dict:
        manager_access(request, authorization)
        row = store.get(message_id)
        if not row:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        return row

    @app.get("/api/inbox/{message_id}/conversation")
    def inbox_conversation(message_id: str, request: Request,
                           authorization: str | None = Header(default=None)) -> list[dict]:
        manager_access(request, authorization)
        return store.conversation(message_id)

    @app.post("/api/demo-message")
    def demo_message(payload: SuggestRequest, request: Request, background: BackgroundTasks,
                     authorization: str | None = Header(default=None)) -> dict[str, str]:
        manager_access(request, authorization)
        message_id = "demo-" + str(uuid.uuid4())
        talk_id = payload.conversation_id or message_id
        item = IncomingMessage(message_id, payload.message, talk_id, None, "demo")
        store.insert(item.id, None, item.talk_id, item.text)
        background.add_task(process_incoming, item)
        return {"id": message_id, "status": "queued"}

    @app.post("/webhooks/amo/{provided_secret}")
    async def amo_webhook(provided_secret: str, request: Request,
                          background: BackgroundTasks) -> dict[str, int]:
        if not settings.webhook_secret or not secrets.compare_digest(
            provided_secret, settings.webhook_secret
        ):
            raise HTTPException(status_code=404, detail="Webhook не найден")
        body = await request.body()
        try:
            messages = parse_incoming(request.headers.get("content-type", ""), body)
        except (ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        accepted = 0
        for item in messages:
            if settings.amo_account_id and item.account_id and item.account_id != settings.amo_account_id:
                raise HTTPException(status_code=403, detail="Неверный amoCRM account_id")
            if store.insert(item.id, item.lead_id, item.talk_id, item.text):
                background.add_task(process_incoming, item)
                accepted += 1
        return {"accepted": accepted}

    return app


app = create_app()
