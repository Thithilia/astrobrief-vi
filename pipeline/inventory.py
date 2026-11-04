"""Public, immutable envelopes for independently reviewed summaries.

Private full texts, evidence quotes, draft history and credentials stay local.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .daily import atomic_json, public_figures, timestamp
from .editorial import contains_html, reading_minutes, review_fingerprint, review_passed, validate_draft
from .store import normalize_doi, paper_id

SUMMARY_KEYS = ("id", "doi", "title", "dek", "journal", "authors", "paper_title", "published_online",
                "issue_date", "first_seen", "generated_at", "reviewed_at", "topic", "reading_minutes",
                "source", "figures", "glossary", "references", "byline", "sections")
SOURCE_KEYS = {"kind", "url", "version", "doi", "sha256", "license"}
FIGURE_KEYS = {"src", "alt", "caption", "credit", "license", "original_url", "source_locator", "sha256"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def figure_path(root: Path, src: str) -> Path:
    if not re.fullmatch(r"/figures/[a-f0-9]{16}/figure-\d+\.(?:png|jpg|jpeg|webp)", src):
        raise ValueError("Hình không thuộc thư mục công khai được phép")
    return root / "public" / src.lstrip("/")


def validate_envelope(record: dict, root: Path, *, check_assets=True) -> dict:
    if set(record) != {"schema_version", "summary", "approval"} or record["schema_version"] != 1:
        raise ValueError("Sai cấu trúc kho bài đã duyệt")
    s, proof = record["summary"], record["approval"]
    if set(s) != set(SUMMARY_KEYS) or set(proof) != {"content_hash", "review_fingerprint", "review", "model"}:
        raise ValueError("Kho chứa trường chưa được phép công khai")
    if (not normalize_doi(s["doi"]) or s["doi"] != normalize_doi(s["doi"])
            or s["id"] != paper_id(s["doi"]) or not review_passed(proof["review"])
            or not re.fullmatch(r"[a-f0-9]{64}", proof["review_fingerprint"])):
        raise ValueError("Bài chưa có bằng chứng duyệt đúng DOI")
    if digest(s) != proof["content_hash"]:
        raise ValueError("Nội dung đã thay đổi sau khi duyệt")
    source = s["source"]
    if set(source) != SOURCE_KEYS or source["doi"] != s["doi"] or source["kind"] not in {"publisher", "arxiv"}:
        raise ValueError("Sai nguồn toàn văn đã duyệt")
    if not re.fullmatch(r"[a-f0-9]{64}", source["sha256"] or ""):
        raise ValueError("Thiếu checksum nguồn")
    urls = [source["url"], *(r["url"] for r in s["references"])]
    if any(not re.match(r"^https?://[^\s]+$", str(u)) for u in urls):
        raise ValueError("URL nguồn không hợp lệ")
    if len(s["sections"]) != 6 or any(set(part) != {"heading", "body"} for part in s["sections"]):
        raise ValueError("Bài cần sáu phần giải thích")
    body = "\n".join(part["body"] for part in s["sections"])
    if not 900 <= len(body.split()) <= 1760 or len(s["glossary"]) < 4:
        raise ValueError("Bài không đạt cấu trúc/độ dài")
    public_text = json.dumps(s, ensure_ascii=False)
    if contains_html(body) or re.search(r"(?:javascript|vbscript|file)\s*:|[A-Za-z]:\\|\.local[/\\]", public_text, re.I):
        raise ValueError("Nội dung công khai có HTML, đường dẫn riêng hoặc URL không an toàn")
    for figure in s["figures"]:
        if set(figure) != FIGURE_KEYS or ("creativecommons.org/licenses/by/" not in figure["license"].lower()
                                          and figure["license"].upper() not in {"CC BY 4.0", "CC-BY-4.0"}):
            raise ValueError("Hình thiếu quyền sử dụng hoặc metadata hợp lệ")
        path = figure_path(root, figure["src"])
        if check_assets and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != figure["sha256"]):
            raise ValueError("Hình đã thay đổi sau khi duyệt")
    return record


def approve(root: Path, paper: dict, source: dict, draft: dict, review: dict, proof: dict,
            *, topic: str, model: str, generated_at: str) -> dict:
    if validate_draft(draft, source) or not review_passed(review):
        raise ValueError("Bản nháp chưa vượt kiểm tra nguồn")
    if proof.get("fingerprint") != review_fingerprint(draft, source):
        raise ValueError("Lần duyệt không khớp phiên bản hiện tại")
    figures = public_figures(root, paper, source, draft)
    for figure in figures:
        figure["sha256"] = hashlib.sha256(figure_path(root, figure["src"]).read_bytes()).hexdigest()
    s = {"id": paper["id"], "doi": paper["doi"], "title": draft["title"], "dek": draft["dek"],
         "journal": paper["journal"], "authors": paper.get("authors", []), "paper_title": paper["title"],
         "published_online": paper.get("published_online"), "issue_date": paper.get("issue_date"),
         "first_seen": paper.get("first_seen"), "generated_at": generated_at,
         "reviewed_at": proof["checked_at"], "topic": topic, "reading_minutes": reading_minutes(draft),
         "source": {key: source.get(key) for key in SOURCE_KEYS}, "figures": figures,
         "glossary": draft["glossary"], "sections": draft["sections"],
         "references": [{"label": "Bài công bố gốc (DOI)", "url": "https://doi.org/" + paper["doi"]},
                        {"label": "Toàn văn đã đọc", "url": source["url"]}],
         "byline": "Tổng hợp tự động bằng Codex"}
    record = {"schema_version": 1, "summary": s,
              "approval": {"content_hash": digest(s), "review_fingerprint": proof["fingerprint"],
                           "review": review, "model": model}}
    validate_envelope(record, root)
    target = root / "content" / "ready" / f"{s['id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != record:
        raise ValueError("Bài đã duyệt là bất biến; cần xử lý phiên bản thay thế rõ ràng")
    atomic_json(target, record)
    return record


def load_inventory(root: Path) -> dict[str, dict]:
    result = {}
    for path in sorted((root / "content" / "ready").glob("*.json")):
        record = validate_envelope(json.loads(path.read_text(encoding="utf-8")), root)
        if path.stem != record["summary"]["id"]:
            raise ValueError("Tên file kho không khớp DOI")
        result[path.stem] = record
    return result


def preview(record: dict, day: str) -> dict:
    s = record["summary"]
    fields = ("id", "doi", "title", "dek", "journal", "paper_title", "generated_at", "topic", "reading_minutes")
    result = {key: s[key] for key in fields}
    result.update(summary_date=day, source={k: s["source"][k] for k in ("kind", "url", "version")},
                  content_hash=record["approval"]["content_hash"],
                  search_text="\n".join(part["body"] for part in s["sections"]))
    if s["figures"]:
        result["image"] = s["figures"][0]["src"]
    return result
