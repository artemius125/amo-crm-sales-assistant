"""SQLite — источник фактов; FTS5/BM25 — индекс для выбора документов."""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import snowballstemmer

WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
STEMMER = snowballstemmer.stemmer("russian")
STOP = {"а", "в", "вы", "да", "для", "до", "и", "из", "или", "как", "какая", "какой",
        "ли", "мне", "мы", "на", "не", "но", "о", "по", "с", "со", "у", "что", "это",
        "я", "здравствуйте", "добрый", "день", "пожалуйста", "нужен", "нужны", "нужно"}


def tokens(text: str) -> list[str]:
    words = [word.lower().replace("ё", "е") for word in WORD.findall(text)]
    return [STEMMER.stemWord(word) if re.search(r"[а-я]", word) else word
            for word in words if len(word) > 1 and word not in STOP]


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    body: str
    kind: str
    source: str
    reviewed_at: str
    product_id: str | None


@dataclass(frozen=True)
class Hit:
    document: Document
    bm25: float


@dataclass(frozen=True)
class Fact:
    id: str
    document_id: str
    product_id: str | None
    category: str
    value: str
    volatile: bool


@dataclass(frozen=True)
class UpsellRule:
    id: str
    product_id: str
    add_on_id: str
    reason: str
    question: str
    trigger_terms: str


class KnowledgeIndex:
    def __init__(self, path: Path):
        if not path.is_file():
            raise ValueError(f"База знаний не найдена: {path}. Выполните amo-assistant init-db")
        self.path = path
        self.connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.documents = {row["id"]: Document(**dict(row)) for row in self.connection.execute(
            "SELECT id,title,body,kind,source,reviewed_at,product_id FROM documents")}
        if not self.documents:
            raise ValueError("В SQLite нет документов базы знаний")
        # Индекс — производное представление. Исходные тексты и факты остаются в SQLite.
        self.fts = sqlite3.connect(":memory:", check_same_thread=False)
        self.fts.row_factory = sqlite3.Row
        self.fts.execute("CREATE VIRTUAL TABLE docs_fts USING fts5(id UNINDEXED,title,body)")
        for doc in self.documents.values():
            self.fts.execute("INSERT INTO docs_fts VALUES (?,?,?)", (
                doc.id, " ".join(tokens(doc.title)), " ".join(tokens(doc.body))))
        self.fts.commit()
        self.aliases: dict[str, set[tuple[str, ...]]] = {}
        for row in self.connection.execute("SELECT product_id,alias FROM product_aliases"):
            self.aliases.setdefault(row["product_id"], set()).add(tuple(tokens(row["alias"])))

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        terms = list(dict.fromkeys(tokens(query)))[:24]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self.lock:
            rows = self.fts.execute(
                "SELECT id,bm25(docs_fts,0.0,3.0,1.0) AS rank FROM docs_fts "
                "WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?", (expression, min(max(limit, 1), 20)),
            ).fetchall()
        return [Hit(self.documents[row["id"]], round(row["rank"], 4)) for row in rows]

    def mentioned_products(self, message: str) -> set[str]:
        terms = set(tokens(message))
        return {product for product, aliases in self.aliases.items()
                if any(alias and set(alias) <= terms for alias in aliases)}

    def facts(self, categories: set[str], product_id: str | None) -> list[Fact]:
        if not categories:
            return []
        placeholders = ",".join("?" for _ in categories)
        query = (f"SELECT id,document_id,product_id,category,value,volatile FROM facts "
                 f"WHERE category IN ({placeholders}) AND (product_id=? OR product_id IS NULL) "
                 "ORDER BY CASE WHEN product_id IS NULL THEN 1 ELSE 0 END,id")
        with self.lock:
            rows = self.connection.execute(query, (*sorted(categories), product_id)).fetchall()
        return [Fact(**{**dict(row), "volatile": bool(row["volatile"])}) for row in rows]

    def upsell(self, product_id: str) -> UpsellRule | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT id,product_id,add_on_id,reason,question,trigger_terms FROM upsell_rules "
                "WHERE product_id=? AND active=1 ORDER BY priority DESC,id LIMIT 1", (product_id,),
            ).fetchone()
        return UpsellRule(**dict(row)) if row else None

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Полное содержимое учебной базы для панели менеджера."""
        queries = {
            "documents": "SELECT id,title,body,kind,source,reviewed_at,product_id FROM documents ORDER BY kind,id",
            "facts": "SELECT f.id,f.document_id,f.product_id,f.category,f.value,f.volatile "
                     "FROM facts AS f JOIN documents AS d ON d.id=f.document_id "
                     "ORDER BY CASE WHEN d.kind='product' THEN 0 ELSE 1 END,d.title,f.category,f.id",
            "aliases": "SELECT product_id,alias FROM product_aliases ORDER BY product_id,alias",
            "rules": "SELECT id,product_id,add_on_id,reason,question,trigger_terms,priority,active FROM upsell_rules ORDER BY priority DESC,id",
        }
        with self.lock:
            return {name: [dict(row) for row in self.connection.execute(query)]
                    for name, query in queries.items()}

    def close(self) -> None:
        self.fts.close()
        self.connection.close()
