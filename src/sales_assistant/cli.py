from __future__ import annotations

import argparse
import sqlite3

import uvicorn

from .config import PROJECT_ROOT, Settings
from .retrieval import KnowledgeIndex


def main() -> None:
    parser = argparse.ArgumentParser(description="amoCRM Sales Assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="запустить HTTP API и панель менеджера")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("init-db", help="создать SQLite и добавить учебные записи без перезаписи изменений")
    sub.add_parser("doctor", help="проверить конфигурацию и индекс базы знаний")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init-db":
        settings.knowledge_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.knowledge_db_path) as db:
            db.executescript((PROJECT_ROOT / "knowledge" / "demo.sql").read_text(encoding="utf-8"))
        print(f"База знаний готова: {settings.knowledge_db_path}")
        return
    if args.command == "doctor":
        index = KnowledgeIndex(settings.knowledge_db_path)
        print(f"Документов в BM25-индексе: {len(index.documents)}")
        print(f"SQLite: {settings.knowledge_db_path}")
        print(f"amoCRM API: {'настроен' if settings.amo_domain and settings.amo_token else 'не настроен'}")
        print(f"Webhook: {'настроен' if settings.webhook_secret else 'не настроен'}")
        print(f"AITUNNEL: {'настроен' if settings.llm_api_key else 'не настроен (локальный режим)'}")
        index.close()
        return
    if args.host not in ("127.0.0.1", "::1", "localhost") and not settings.app_api_key:
        parser.error("Для удалённого доступа необходимо задать APP_API_KEY")
    uvicorn.run("sales_assistant.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
