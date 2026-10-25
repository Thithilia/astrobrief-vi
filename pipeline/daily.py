"""Resumable daily editor: source -> draft -> factual review -> static content."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid
from zoneinfo import ZoneInfo

import jsonschema
import yaml

from .codex_runner import run_structured, configuration, CodexUnavailable, CodexQuotaExceeded
from .editorial import (selection_prompt, draft_prompt, review_prompt, validate_draft,
                        review_passed, reading_minutes, review_fingerprint)
from .fulltext import acquire_fulltext, FullTextUnavailable
from .store import normalize_doi

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def process_lock(root: Path, name: str):
    """An OS-held lock releases after crashes, unlike persistent sentinel files."""
    lock_dir = root / ".local" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / f"{name}.lock").open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"Phiên {name} đang chạy.") from exc
        except OSError as exc:
            raise RuntimeError(f"Phiên {name} đang chạy.") from exc
        try:
            yield
        finally:
            try:
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except ImportError:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_jobs(store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS editorial_jobs (
        day TEXT NOT NULL, doi TEXT NOT NULL, state TEXT NOT NULL,
        error TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(day,doi))""")
    store.conn.commit()


def set_job(store, day, doi, state, error=None):
    store.conn.execute("""INSERT INTO editorial_jobs(day,doi,state,error,updated_at) VALUES(?,?,?,?,?)
        ON CONFLICT(day,doi) DO UPDATE SET state=excluded.state,error=excluded.error,updated_at=excluded.updated_at""",
        (day, doi, state, error, timestamp()))
    store.conn.commit()


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def cached_json(path: Path, schema_name: str) -> dict | None:
    """A killed process can leave an old/truncated cache; it is never authoritative."""
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "pipeline" / "schemas" / f"{schema_name}.json").read_text(encoding="utf-8"))
        jsonschema.validate(value, schema)
        return value
    except (OSError, ValueError, jsonschema.ValidationError):
        return None


def public_figures(root: Path, paper: dict, source: dict, draft: dict) -> list[dict]:
    result = []
    for explanation in draft.get("figure_explanations", [])[:2]:
        original = source.get("figures", [])[explanation["index"]]
        image = original.get("image_path") or original.get("src")
        license_name = str(original.get("license") or "")
        # Local page renders are vision aids only; never republish a full PDF page.
        if (not image or not Path(image).is_file() or original.get("local_only")
                or original.get("public_safe") is not True):
            continue
        if "creativecommons.org/licenses/by/" not in license_name.lower() and license_name.upper() not in ("CC BY 4.0", "CC-BY-4.0"):
            continue
        suffix = Path(image).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        target = root / "public" / "figures" / paper["id"] / f"figure-{explanation['index']}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, target)
        result.append({"src": "/figures/" + paper["id"] + "/" + target.name,
                       "alt": explanation["alt_vi"], "caption": explanation["caption_vi"],
                       "credit": original.get("credit") or f"{paper['title']} — {paper['doi']}",
                       "license": license_name, "original_url": original.get("original_url") or source["url"],
                       "source_locator": original.get("source_locator", "")})
    return result


def write_summary(root: Path, summary: dict, draft: dict) -> Path:
    destination = root / "content" / "summaries" / f"{summary['id']}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ("id", "doi", "title", "dek", "journal", "authors", "paper_title", "published_online",
              "issue_date", "first_seen", "summary_date", "generated_at", "topic", "reading_minutes",
              "source", "figures", "glossary", "references", "byline")
    frontmatter = {k: summary.get(k) for k in fields}
    body = "\n\n".join(f"## {part['heading']}\n\n{part['body']}" for part in draft["sections"])
    text = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n"
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)
    return destination


def recover_summary_files(store, root: Path) -> int:
    """SQLite is authoritative for the daily cap and for publication eligibility.

    Persisted reviewed drafts repair a crash between committing SQLite and the
    atomic Markdown write. Unknown public Markdown is not silently published.
    """
    summaries = {summary["id"]: summary for summary in store.summaries()}
    directory = root / "content" / "summaries"
    for existing in directory.glob("*.md"):
        if existing.stem not in summaries:
            raise RuntimeError(f"Summary {existing.name} chưa được đăng ký trong SQLite; giữ lại để đối chiếu trước khi xuất bản.")
    recovered = 0
    for summary in summaries.values():
        destination = directory / f"{summary['id']}.md"
        if destination.exists():
            continue
        if not summary.get("draft") or not review_passed(summary.get("review", {})):
            raise RuntimeError(f"Thiếu bản nháp đã kiểm tra để phục hồi summary {summary['id']}.")
        write_summary(root, summary, summary["draft"])
        recovered += 1
    return recovered


def candidate_pool(papers: list[dict], root: Path) -> tuple[list[dict], set[str]]:
    """Keep recent discoveries and already readable older papers visible to selection."""
    ordered = sorted(papers, key=lambda p: (p.get("published_online") or "", p.get("first_seen") or ""), reverse=True)
    discovered = sorted(papers, key=lambda p: (p.get("first_seen") or "", p.get("published_online") or ""), reverse=True)
    ready = []
    for paper in ordered:
        path = root / ".local" / "cache" / "fulltext" / paper["id"] / "source.json"
        if not path.is_file():
            continue
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            if (source.get("complete") and normalize_doi(source.get("doi")) == paper["doi"] and source.get("text")
                    and source.get("kind") in {"publisher", "arxiv"} and source.get("sha256")):
                ready.append(dict(paper, fulltext_ready=True))
        except (OSError, ValueError):
            continue
    ready_dois = {paper["doi"] for paper in ready}
    result = {}
    for paper in [*ordered[:100], *discovered[:50], *ready]:
        result[paper["doi"]] = dict(paper, fulltext_ready=paper["doi"] in ready_dois)
    return list(result.values()), ready_dois


def run_daily(store, root: Path = ROOT, now: datetime | None = None, limit: int = 5,
              catch_up: bool = False, runner=run_structured, acquire=acquire_fulltext,
              progress=print) -> dict:
    current = now or datetime.now(TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TZ)
    current = current.astimezone(TZ)
    day = current.date().isoformat()
    limit = max(0, min(int(limit), 5))
    if catch_up and current.hour < 7:
        return {"date": day, "status": "not_due", "created": 0}
    with process_lock(root, "daily"):
        prepare_jobs(store)
        recover_summary_files(store, root)
        already = store.summaries()
        existing_dois = {s["doi"] for s in already}
        today = sum(s.get("summary_date") == day for s in already)
        if today >= limit:
            return {"date": day, "status": "complete", "created": 0, "total_today": today}
        failed = {r[0] for r in store.conn.execute(
            "SELECT doi FROM editorial_jobs WHERE day=? AND state IN ('held','no_fulltext')", (day,))}
        papers = [p for p in store.papers() if p.get("doi") and p["doi"] not in existing_dois
                  and p["doi"] not in failed and p.get("kind") not in ("correction", "editorial", "review")]
        # Pending papers do not expire because their online date precedes today.
        papers, ready_dois = candidate_pool(papers, root)
        # Full text is an eligibility condition. If a complete readable pool is
        # already available, rank that pool instead of repeatedly preferring
        # inaccessible recent titles over verified pending papers.
        if len(ready_dois) >= limit - today:
            papers = [p for p in papers if p["doi"] in ready_dois]
        if not papers:
            return {"date": day, "status": "no_candidates", "created": 0, "total_today": today}
        work = root / ".local" / "runs" / day
        work.mkdir(parents=True, exist_ok=True)
        report = {"date": day, "status": "running", "created": 0, "total_today": today, "held": []}
        try:
            selection_path = work / "selection.json"
            selection = cached_json(selection_path, "selection")
            if selection is not None and ready_dois:
                selected_dois = {normalize_doi(item.get("doi")) for item in selection.get("candidates", [])[:15]}
                state = cached_json(work / "selection-input.json", "selection-input")
                previous_ready = set(state.get("ready_dois", [])) if state else selected_dois
                if ready_dois - previous_ready:
                    selection = None
            if selection is None:
                progress("Đang chọn ứng viên từ danh sách bài mới…", flush=True)
                selection = runner(selection_prompt(papers), "selection", work)
                atomic_json(selection_path, selection)
                atomic_json(work / "selection-input.json", {"ready_dois": sorted(ready_dois)})
            by_doi = {p["doi"]: p for p in papers}
            if not any(normalize_doi(item.get("doi", "")) in by_doi
                       for item in selection.get("candidates", [])[:15]):
                selection = runner(selection_prompt(papers), "selection", work)
                atomic_json(selection_path, selection)
                atomic_json(work / "selection-input.json", {"ready_dois": sorted(ready_dois)})
            candidates = []
            seen = set()
            for item in selection.get("candidates", [])[:15]:
                doi = normalize_doi(item["doi"])
                if doi in by_doi and doi not in seen:
                    seen.add(doi)
                    candidates.append((by_doi[doi], item))
            for paper, choice in candidates:
                if report["total_today"] >= limit:
                    break
                if paper["doi"] in {s["doi"] for s in store.summaries()}:
                    continue
                progress(f"Đọc toàn văn: {paper['journal']} — {paper['doi']}", flush=True)
                set_job(store, day, paper["doi"], "source")
                try:
                    source = acquire(paper, root / ".local" / "cache", allow_arxiv=True)
                except FullTextUnavailable as exc:
                    set_job(store, day, paper["doi"], "no_fulltext", str(exc))
                    report["held"].append({"doi": paper["doi"], "reason": "no_fulltext"})
                    continue
                if len(source.get("text", "")) > 450000:
                    set_job(store, day, paper["doi"], "held", "Toàn văn dài hơn gói đọc hiện tại; cần đọc phân đoạn.")
                    continue
                paper_work = work / paper["id"]
                paper_work.mkdir(parents=True, exist_ok=True)
                source = dict(source)
                source["figures"] = [f for f in source.get("figures", [])
                                     if (f.get("image_path") or f.get("src"))
                                     and Path(f.get("image_path") or f.get("src")).is_file()][:3]
                images = [str(f.get("image_path") or f.get("src")) for f in source["figures"]]
                draft_path = paper_work / "draft.json"
                repair = ""
                draft = None
                review = None
                for attempt in range(2):
                    set_job(store, day, paper["doi"], "draft")
                    progress(f"Viết và kiểm tra {paper['doi']} (lượt {attempt+1})…", flush=True)
                    draft = cached_json(draft_path, "draft") if attempt == 0 else None
                    if draft is None:
                        draft = runner(draft_prompt(paper, source, repair), "draft", paper_work, images=images)
                        atomic_json(draft_path, draft)
                    issues = validate_draft(draft, source)
                    if issues:
                        repair = "\n".join(issues)
                        continue
                    set_job(store, day, paper["doi"], "review")
                    fingerprint = review_fingerprint(draft, source)
                    proof_path = paper_work / "review-provenance.json"
                    try:
                        proof = json.loads(proof_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        proof = {}
                    review = cached_json(paper_work / "review.json", "review")
                    if proof.get("fingerprint") != fingerprint or not review or not review_passed(review):
                        review = runner(review_prompt(paper, source, draft), "review", paper_work, images=images)
                        atomic_json(paper_work / "review.json", review)
                        atomic_json(proof_path, {"fingerprint": fingerprint, "checked_at": timestamp()})
                    if review_passed(review):
                        break
                    repair = "\n".join(review.get("issues", [])) or "Các kiểm tra nguồn chưa đạt."
                if draft is None or validate_draft(draft, source) or not review or not review_passed(review):
                    set_job(store, day, paper["doi"], "held", repair or "Chưa vượt kiểm tra nguồn.")
                    report["held"].append({"doi": paper["doi"], "reason": "review"})
                    continue
                figures = public_figures(root, paper, source, draft)
                summary = {"id": paper["id"], "doi": paper["doi"], "title": draft["title"], "dek": draft["dek"],
                           "journal": paper["journal"], "authors": paper.get("authors", []), "paper_title": paper["title"],
                           "published_online": paper.get("published_online"), "issue_date": paper.get("issue_date"),
                           "first_seen": paper.get("first_seen"), "summary_date": day, "generated_at": timestamp(),
                           "topic": choice.get("topic", "other"), "selection_rationale": choice.get("rationale", ""),
                           "reading_minutes": reading_minutes(draft),
                           "source": {k: source.get(k) for k in ("kind", "url", "version", "doi", "sha256", "license")},
                           "figures": figures, "glossary": draft["glossary"],
                           "references": [{"label": "Bài công bố gốc (DOI)", "url": f"https://doi.org/{paper['doi']}"},
                                          {"label": "Phiên bản toàn văn đã đọc", "url": source["url"]}],
                           "byline": "Tổng hợp tự động bằng Codex", "model": configuration().get("model", "Codex default"),
                           "evidence": draft["evidence"], "review": review,
                           "search_text": "\n".join(s["body"] for s in draft["sections"]), "draft": draft}
                # Commit the authoritative daily count first. A stopped file write
                # is reconstructed from this reviewed draft before any export.
                store.save_summary(summary)
                write_summary(root, summary, draft)
                set_job(store, day, paper["doi"], "ready")
                report["created"] += 1
                report["total_today"] += 1
                progress(f"Đã kiểm tra và tạo summary {report['total_today']}/5: {draft['title']}", flush=True)
            report["status"] = "complete" if report["total_today"] >= limit else "partial"
        except CodexQuotaExceeded as exc:
            report["status"], report["error"] = "quota_wait", str(exc)
        except CodexUnavailable as exc:
            report["status"], report["error"] = "codex_unavailable", str(exc)
        finally:
            store.set_state("daily:last_report", report)
            atomic_json(work / "report.json", report)
        return report
