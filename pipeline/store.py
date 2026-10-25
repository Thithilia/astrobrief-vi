"""Small SQLite store. Full texts and credentials never enter public exports."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_doi(value: str | None) -> str:
    value = html.unescape(unquote(str(value or ""))).strip().strip("<>")
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", value, flags=re.I)
    value = value.strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value, flags=re.I):
        return ""
    return value.lower()


def paper_id(doi: str) -> str:
    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError("A valid DOI is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _nonempty(value) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _date_quality(value: str | None, precision: str | None = None) -> int:
    if not value:
        return 0
    inferred = 3 if len(str(value)) >= 10 else 2 if len(str(value)) >= 7 else 1
    return {"year": 1, "month": 2, "day": 3}.get(precision, inferred)


def merge_paper(old: dict | None, new: dict) -> dict:
    """Keep identity/first discovery stable, and never replace a known date with null."""
    doi = normalize_doi(new.get("doi"))
    if not doi:
        raise ValueError("Invalid or missing DOI")
    current = dict(old or {})
    for key, value in new.items():
        if not _nonempty(value):
            continue
        if key in {"id", "doi", "first_seen", "published_online", "online_date_precision", "_online_source"}:
            continue
        if key == "authors" and len(current.get("authors", [])) > len(value):
            continue
        if key == "abstract" and len(current.get("abstract", "")) > len(value):
            continue
        if key == "topic" and value == "other" and current.get("topic") not in (None, "other"):
            continue
        if key == "kind" and value == "unknown" and current.get("kind") not in (None, "unknown"):
            continue
        if key == "source_url" and current.get(key) and re.match(r"https?://(?:dx\.)?doi\.org/", value):
            continue
        if key == "_metadata_sources":
            current[key] = list(dict.fromkeys([*current.get(key, []), *value]))
            continue
        current[key] = value
    old_date, new_date = current.get("published_online"), new.get("published_online")
    old_quality = _date_quality(old_date, current.get("online_date_precision"))
    new_quality = _date_quality(new_date, new.get("online_date_precision"))
    if new_date and (not old_date or new_quality > old_quality or (
        new_quality == old_quality
        and new.get("_online_source") == "rss"
        and current.get("_online_source") != "rss"
    )):
        current["published_online"] = new_date
        current["online_date_precision"] = new.get("online_date_precision", "day")
        current["_online_source"] = new.get("_online_source", "crossref")
    current.setdefault("published_online", None)
    current.setdefault("online_date_precision", None)
    first_seen = [v for v in ((old or {}).get("first_seen"), new.get("first_seen")) if v]
    current["first_seen"] = min(first_seen) if first_seen else utc_now()
    current["updated_at"] = new.get("updated_at") or utc_now()
    current["id"] = paper_id(doi)
    current["doi"] = doi
    current.setdefault("authors", [])
    current.setdefault("abstract", "")
    current.setdefault("source_url", "https://doi.org/" + doi)
    current.setdefault("kind", "unknown")
    current.setdefault("topic", "other")
    for field in ("issue_date", "volume", "issue", "article_number", "pdf_url", "arxiv_id"):
        current.setdefault(field, None)
    return current


class Store:
    def __init__(self, db_path: Path | str = ROOT / ".local" / "state.sqlite"):
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS papers (
                doi TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                journal TEXT NOT NULL, published_online TEXT,
                first_seen TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS papers_journal_date ON papers(journal, published_online);
            CREATE TABLE IF NOT EXISTS summaries (
                doi TEXT PRIMARY KEY REFERENCES papers(doi), id TEXT NOT NULL UNIQUE,
                summary_date TEXT NOT NULL, generated_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.conn.commit()

    @property
    def connection(self):
        return self.conn

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.conn.close()

    def get_paper(self, doi: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM papers WHERE doi=?", (normalize_doi(doi),)).fetchone()
        return json.loads(row[0]) if row else None

    def papers(self) -> list[dict]:
        rows = self.conn.execute("SELECT payload FROM papers ORDER BY first_seen DESC, doi").fetchall()
        return [json.loads(row[0]) for row in rows]

    def upsert_papers(self, papers: list[dict]) -> int:
        """Return the number of new identities, not the number of refreshed records."""
        added = 0
        with self.conn:
            for paper in papers:
                doi = normalize_doi(paper.get("doi"))
                if not doi:
                    raise ValueError("Cannot store a paper without a valid DOI")
                old = self.get_paper(doi)
                merged = merge_paper(old, paper)
                if not merged.get("journal"):
                    raise ValueError("A journal id is required")
                if old and old.get("journal") != merged["journal"]:
                    raise ValueError("A DOI cannot be silently relabelled as another journal")
                added += old is None
                self.conn.execute("""
                    INSERT INTO papers(doi,id,journal,published_online,first_seen,payload)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(doi) DO UPDATE SET
                    published_online=excluded.published_online,payload=excluded.payload
                """, (doi, merged["id"], merged["journal"], merged.get("published_online"),
                      merged["first_seen"], json.dumps(merged, ensure_ascii=False)))
        return int(added)

    def get_state(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key: str, value):
        with self.conn:
            self.conn.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, json.dumps(value, ensure_ascii=False)))

    def summaries(self) -> list[dict]:
        return [json.loads(row[0]) for row in self.conn.execute(
            "SELECT payload FROM summaries ORDER BY summary_date DESC,generated_at DESC,doi")]

    def save_summary(self, summary: dict):
        doi = normalize_doi(summary.get("doi"))
        if not summary.get("review", {}).get("passed") is True:
            raise ValueError("Only a summary that passed factual review can be saved")
        paper = self.get_paper(doi)
        if not paper:
            raise ValueError("Summary must reference an existing DOI")
        summary = dict(summary, doi=doi, id=paper["id"])
        for key in ("summary_date", "generated_at"):
            if not summary.get(key):
                raise ValueError(f"Missing summary field: {key}")
        with self.conn:
            self.conn.execute("""
                INSERT INTO summaries(doi,id,summary_date,generated_at,payload) VALUES(?,?,?,?,?)
                ON CONFLICT(doi) DO UPDATE SET summary_date=excluded.summary_date,
                generated_at=excluded.generated_at,payload=excluded.payload
            """, (doi, summary["id"], summary["summary_date"], summary["generated_at"],
                  json.dumps(summary, ensure_ascii=False)))
