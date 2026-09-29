from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    knowledge_db_path: Path
    database_path: Path
    amo_domain: str
    amo_token: str
    amo_account_id: str
    webhook_secret: str
    publish_notes: bool
    app_api_key: str
    llm_api_key: str
    llm_model: str
    amo_polling: bool = False
    amo_widget_id: str = ""
    amo_widget_hash: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        domain = os.getenv("AMO_DOMAIN", "").strip().lower()
        if domain:
            parsed = urlparse("https://" + domain)
            if parsed.hostname != domain or not domain.endswith((".amocrm.ru", ".amocrm.com")):
                raise ValueError("AMO_DOMAIN должен быть поддоменом amocrm.ru или amocrm.com")
        return cls(
            knowledge_db_path=Path(os.getenv("KNOWLEDGE_DB_PATH", PROJECT_ROOT / ".data" / "knowledge.sqlite3")),
            database_path=Path(os.getenv("DATABASE_PATH", PROJECT_ROOT / ".data" / "assistant.sqlite3")),
            amo_domain=domain,
            amo_token=os.getenv("AMO_TOKEN", "").strip(),
            amo_account_id=os.getenv("AMO_ACCOUNT_ID", "").strip(),
            webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
            publish_notes=os.getenv("PUBLISH_NOTES", "false").lower() in ("1", "true", "yes"),
            app_api_key=os.getenv("APP_API_KEY", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
            amo_polling=os.getenv("AMO_POLLING", "false").lower() in ("1", "true", "yes"),
            amo_widget_id=os.getenv("AMO_WIDGET_ID", "").strip(),
            amo_widget_hash=os.getenv("AMO_WIDGET_HASH", "").strip(),
        )
