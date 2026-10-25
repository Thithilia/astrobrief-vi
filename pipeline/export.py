"""Explicit allow-list export; no raw PDFs, abstracts, credentials or local paths."""

from __future__ import annotations

import json
import re
from contextlib import ExitStack
from pathlib import Path
import time
import uuid

from .journals import JOURNALS
from .store import Store, utc_now

PAPER_FIELDS = (
    "id", "doi", "title", "journal", "authors", "published_online", "online_date_precision",
    "issue_date", "first_seen", "volume", "issue", "article_number", "source_url", "kind", "topic",
)
SUMMARY_FIELDS = (
    "id", "doi", "title", "dek", "journal", "paper_title", "summary_date", "generated_at", "topic", "reading_minutes",
)


def _public_url(value: str | None) -> str | None:
    return value if value and re.match(r"^https?://", value) else None


def export_catalog(store: Store, root: Path) -> Path:
    # Import lazily: daily orchestration also uses this module when publishing.
    from .daily import process_lock

    root = Path(root)
    deadline = time.monotonic() + 30
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(process_lock(root, "export"))
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        # Read only after acquiring the lock, so a waiting exporter sees commits
        # made while the preceding exporter was still running.
        return _export_catalog_locked(store, root)


def _export_catalog_locked(store: Store, root: Path) -> Path:
    health = store.get_state("journal_health", {})
    summaries = store.summaries()
    by_doi = {summary["doi"]: summary for summary in summaries}
    papers = []
    for paper in store.papers():
        public = {field: paper.get(field) for field in PAPER_FIELDS}
        public["has_summary"] = paper["doi"] in by_doi
        if public["has_summary"]:
            public["summary_id"] = by_doi[paper["doi"]]["id"]
            public["topic"] = by_doi[paper["doi"]].get("topic", paper.get("topic", "other"))
        papers.append(public)
    previews = []
    for summary in summaries:
        preview = {field: summary.get(field) for field in SUMMARY_FIELDS}
        source = summary.get("source", {})
        preview["source"] = {"kind": source.get("kind"), "url": _public_url(source.get("url")),
                             "version": source.get("version")}
        figures = summary.get("figures", [])
        if figures and figures[0].get("src"):
            preview["image"] = figures[0]["src"]
        sections = summary.get("sections", [])
        texts = [str(section.get("body", "")) for section in sections if isinstance(section, dict)]
        if summary.get("body"):
            texts.append(str(summary["body"]))
        if summary.get("search_text"):
            texts.append(str(summary["search_text"]))
        preview["search_text"] = " ".join(texts)
        previews.append(preview)
    journals = []
    for journal in JOURNALS:
        state = health.get(journal["id"], {})
        journals.append({
            "id": journal["id"], "name": journal["name"], "short": journal["short"],
            "url": journal["url"], "status": state.get("status", "pending"),
            "last_success": state.get("last_success"), "last_attempt": state.get("last_attempt"),
            "error": state.get("error"),
        })
    document = {"generated_at": utc_now(), "timezone": "Asia/Saigon", "journals": journals,
                "papers": papers, "summaries": previews}
    target = root / "public" / "data" / "catalog.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
