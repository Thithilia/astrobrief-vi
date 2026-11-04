"""Durable, cross-day editorial worker; approval never means publication."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

from .codex_runner import run_structured, configuration, CodexQuotaExceeded, CodexUnavailable, CodexAuthenticationRequired
from .daily import atomic_json, cached_json, process_lock, timestamp
from .editorial import (selection_prompt, draft_prompt, review_prompt, repair_prompt, apply_repairs,
                        validate_draft, review_passed, review_fingerprint)
from .fulltext import CACHE_VERSION, FullTextUnavailable, acquire_fulltext
from .inventory import approve, load_inventory
from .release import ledger, save_health

MAX_REPAIRS = 3
RESERVE_TARGET = 35


def setup(store):
    store.conn.executescript("""
        CREATE TABLE IF NOT EXISTS editorial_items (
            doi TEXT PRIMARY KEY REFERENCES papers(doi), state TEXT NOT NULL DEFAULT 'pending',
            retry_at TEXT, repair_count INTEGER NOT NULL DEFAULT 0, source_sha TEXT,
            error TEXT, topic TEXT, rationale TEXT, rank INTEGER, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS editorial_attempts (
            id INTEGER PRIMARY KEY, doi TEXT, stage TEXT, started_at TEXT, elapsed_seconds REAL,
            status TEXT, usage TEXT, error TEXT
        );
    """)
    store.conn.commit()


def update(store, doi, state, **values):
    allowed={"retry_at","repair_count","source_sha","error","topic","rationale","rank"}
    if not set(values).issubset(allowed): raise ValueError("Unknown queue field")
    assignments=["state=?","updated_at=?"]+[f"{key}=?" for key in values]
    store.conn.execute("UPDATE editorial_items SET "+",".join(assignments)+" WHERE doi=?",
                       [state,timestamp(),*values.values(),doi])
    store.conn.commit()


def seed(store, root: Path):
    setup(store)
    published={r["doi"] for r in ledger(root)["releases"]}
    approved={r["summary"]["doi"] for r in load_inventory(root).values()}
    for p in store.papers():
        if p.get("kind") in {"correction","editorial","review"}: continue
        if store.conn.execute("SELECT 1 FROM editorial_items WHERE doi=?",(p["doi"],)).fetchone(): continue
        state="published" if p["doi"] in published else "approved" if p["doi"] in approved else "pending"
        store.conn.execute("INSERT INTO editorial_items(doi,state,updated_at) VALUES(?,?,?)",(p["doi"],state,timestamp()))
        # Preserve the latest real pre-migration draft and its bounded repair count.
        candidates=sorted((root/".local/runs").glob(f"*/{p['id']}/draft.json"))
        if candidates and state=="pending":
            old=candidates[-1].parent
            target=root/".local/editorial"/p["id"]; target.mkdir(parents=True,exist_ok=True)
            for name in ("draft.json","review.json","review-provenance.json"):
                if (old/name).is_file() and not (target/name).exists(): shutil.copyfile(old/name,target/name)
            try:
                row=store.conn.execute("SELECT repair_attempts FROM editorial_jobs WHERE doi=? ORDER BY day DESC LIMIT 1",(p["doi"],)).fetchone()
                if row: store.conn.execute("UPDATE editorial_items SET repair_count=? WHERE doi=?",(row[0],p["doi"]))
            except Exception:
                # Legacy installations may not have the old table/column.
                pass
    for doi in published:
        store.conn.execute("UPDATE editorial_items SET state='published',retry_at=NULL WHERE doi=?",(doi,))
    store.conn.commit()


def cached_source(root: Path, paper: dict):
    path=root/".local/cache/fulltext"/paper["id"]/"source.json"
    try:
        s=json.loads(path.read_text(encoding="utf-8"))
        text_path=Path(s["text_path"])
        if (s.get("cache_version")!=CACHE_VERSION or s.get("doi")!=paper["doi"] or not s.get("complete")
                or s.get("kind") not in {"publisher","arxiv"} or not s.get("sha256")
                or hashlib.sha256(text_path.read_bytes()).hexdigest()!=s.get("text_sha256")):
            return None
        s["text"]=text_path.read_text(encoding="utf-8")
        return s
    except (OSError,ValueError,KeyError): return None


def heartbeat(store, root: Path, report: dict, *, stage=None, doi=None):
    report["heartbeat_at"]=timestamp()
    if stage: report["stage"]=stage
    report["doi"]=doi
    counts=dict(store.conn.execute("SELECT state,COUNT(*) FROM editorial_items GROUP BY state").fetchall())
    report["queue"]=counts
    store.set_state("producer:last_report",report)
    atomic_json(root/"public/data/producer.json",report)
    save_health(root)


def source_failure(store, paper, exc):
    # Preserve URL-by-URL reasons and schedule real retries across day boundaries.
    detail={"reason":exc.reason,"attempts":exc.attempts}
    reasons={a.get("reason") for a in exc.attempts}
    seconds=exc.retry_after or (6*3600 if reasons & {"http_403","http_401","captcha_or_access_block"} else 3600)
    retry=(datetime.now(timezone.utc)+timedelta(seconds=max(60,seconds))).isoformat().replace("+00:00","Z")
    update(store,paper["doi"],"waiting_source",error=json.dumps(detail,ensure_ascii=False),retry_at=retry)


def eligible(store):
    stamp=timestamp()
    return {r["doi"]:dict(r) for r in store.conn.execute(
        "SELECT * FROM editorial_items WHERE state NOT IN ('published','approved','needs_attention') AND (retry_at IS NULL OR retry_at<=?)",(stamp,))}


def prepare_sources(store, root: Path, *, target=30, budget_seconds=600, acquire=acquire_fulltext, progress=print):
    start=time.monotonic(); seed(store,root); ready=0; tried=0
    with process_lock(root,"sources"):
        from .repository_sources import discover_leads
        discovery=discover_leads(store,root)
        items=eligible(store)
        papers=[p for p in store.papers() if p["doi"] in items]
        papers.sort(key=lambda p:(bool(p.get("repository_url") or p.get("repository_pdf_url")),p.get("published_online") or "",p["first_seen"]),reverse=True)
        for p in papers:
            if cached_source(root,p):
                if items[p["doi"]]["state"] in {"pending","waiting_source","source_ready"}:
                    update(store,p["doi"],"source_ready",retry_at=None)
                ready+=1
        for p in papers:
            if ready>=target or time.monotonic()-start>=budget_seconds: break
            if cached_source(root,p): continue
            tried+=1
            progress(f"Chuẩn bị nguồn: {p['doi']}",flush=True)
            try:
                s=acquire(p,root/".local/cache",allow_arxiv=True)
                update(store,p["doi"],"source_ready",retry_at=None,source_sha=s["sha256"],error=None); ready+=1
            except FullTextUnavailable as exc: source_failure(store,p,exc)
    result={"status":"sources_ready" if ready>=target else "waiting_source","ready":ready,"target":target,"attempted":tried,"discovery":discovery,"heartbeat_at":timestamp()}
    store.set_state("sources:last_report",result)
    return result


class BudgetExpired(Exception): pass


def produce(store, root: Path, *, target=RESERVE_TARGET, max_items=5, budget_seconds=7200,
            runner=run_structured, acquire=acquire_fulltext, progress=print, after_approval=None):
    start=time.monotonic(); root=Path(root)
    report={"status":"running","started_at":timestamp(),"created":0,"reserve_target":target,
            "processed":0,"held":[],"stage":"starting"}
    with process_lock(root,"producer"):
        seed(store,root)
        wait=store.get_state("producer:retry_at")
        if wait and wait>timestamp():
            report.update(status=store.get_state("producer:wait_reason","waiting_quota"),next_retry_at=wait)
            heartbeat(store,root,report); return report
        visited=set()
        active=None

        def call(prompt,schema,work,images=None):
            remaining=budget_seconds-(time.monotonic()-start)
            if remaining<10: raise BudgetExpired()
            heartbeat(store,root,report,stage=schema,doi=active)
            begun=timestamp(); tick=time.monotonic(); status="ok"; error=None; usage={}
            previous={p.name for p in work.glob("*.events.jsonl")}
            try:
                return runner(prompt,schema,work,images=images or [],timeout=min(1200,int(remaining)))
            except Exception as exc:
                status=type(exc).__name__; error=str(exc); raise
            finally:
                for file in work.glob("*.events.jsonl"):
                    if file.name in previous: continue
                    for line in file.read_text(encoding="utf-8",errors="replace").splitlines():
                        try: event=json.loads(line)
                        except ValueError: continue
                        if event.get("type")=="turn.completed": usage=event.get("usage",{})
                store.conn.execute("INSERT INTO editorial_attempts(doi,stage,started_at,elapsed_seconds,status,usage,error) VALUES(?,?,?,?,?,?,?)",
                                   (active,schema,begun,time.monotonic()-tick,status,json.dumps(usage),error))
                store.conn.commit()

        try:
            while report["created"]<max_items and time.monotonic()-start<budget_seconds:
                published={r["id"] for r in ledger(root)["releases"]}
                inventory=load_inventory(root)
                if len(set(inventory)-published)>=target:
                    report["status"]="stock_ready"; break
                items=eligible(store)
                papers=[p for p in store.papers() if p["doi"] in items and p["doi"] not in visited
                        and p["id"] not in published and p["id"] not in inventory]
                if not papers:
                    report["status"]="waiting_source"; break
                ready=[p for p in papers if cached_source(root,p)]
                if not ready:
                    # Deterministic source discovery needs no Codex quota. Every
                    # exhausted batch is followed by another within this budget.
                    p=max(papers,key=lambda p:(p.get("published_online") or "",p["first_seen"]))
                    active=p["doi"]; heartbeat(store,root,report,stage="source",doi=active)
                    try:
                        with process_lock(root,"sources"):
                            s=acquire(p,root/".local/cache",allow_arxiv=True)
                        update(store,p["doi"],"source_ready",source_sha=s["sha256"],retry_at=None,error=None)
                    except FullTextUnavailable as exc:
                        source_failure(store,p,exc); visited.add(p["doi"])
                    except RuntimeError:
                        report["status"]="waiting_source"; break
                    continue
                ready.sort(key=lambda p:(p.get("published_online") or "",p["first_seen"]),reverse=True)
                ranked=[p for p in ready if items[p["doi"]].get("rank") is not None]
                if not ranked:
                    work=root/".local/editorial"; work.mkdir(parents=True,exist_ok=True)
                    selection=call(selection_prompt([dict(p,fulltext_ready=True) for p in ready[:15]]),"selection",work)
                    allowed={p["doi"] for p in ready[:15]}
                    for rank,choice in enumerate(selection["candidates"][:15]):
                        if choice["doi"] in allowed:
                            update(store,choice["doi"],"source_ready",rank=rank,topic=choice["topic"],rationale=choice["rationale"])
                    # A malformed/empty shortlist cannot spin forever.
                    if not selection["candidates"] or not any(c["doi"] in allowed for c in selection["candidates"]):
                        report["status"]="needs_attention"; report["error"]="Chọn bài không trả ứng viên đủ điều kiện"; break
                    continue
                p=min(ranked,key=lambda p:items[p["doi"]]["rank"])
                active=p["doi"]; visited.add(active); report["processed"]+=1
                s=cached_source(root,p)
                if len(s["text"])>450000:
                    update(store,active,"needs_attention",error="Cần đọc toàn văn theo phân đoạn"); continue
                s=dict(s); s["figures"]=[f for f in s.get("figures",[]) if (f.get("image_path") or f.get("src")) and Path(f.get("image_path") or f.get("src")).is_file()][:3]
                images=[str(f.get("image_path") or f.get("src")) for f in s["figures"]]
                work=root/".local/editorial"/p["id"]; work.mkdir(parents=True,exist_ok=True)
                draft_path=work/"draft.json"; d=cached_json(draft_path,"draft")
                meta_path=work/"draft-meta.json"
                try:
                    meta=json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"generated_at":timestamp(),"source_sha":s["sha256"]}
                except (ValueError,OSError):
                    update(store,active,"needs_attention",error="Checkpoint phiên bản nguồn bị hỏng; giữ bản nháp để đối chiếu");continue
                if meta["source_sha"]!=s["sha256"]:
                    update(store,active,"needs_attention",error="Phiên bản nguồn đã thay đổi; cần đối chiếu bản nháp"); continue
                atomic_json(meta_path,meta)
                if d is None:
                    update(store,active,"drafting"); progress(f"Viết bản nháp: {active}",flush=True)
                    d=call(draft_prompt(p,s),"draft",work,images); atomic_json(draft_path,d)
                while True:
                    errors=validate_draft(d,s); review=None
                    if not errors:
                        update(store,active,"reviewing"); fingerprint=review_fingerprint(d,s)
                        proof_path=work/"review-provenance.json"
                        try: proof=json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.exists() else {}
                        except (ValueError,OSError): proof={}
                        review=cached_json(work/"review.json","review")
                        if proof.get("fingerprint")!=fingerprint or not review:
                            review=call(review_prompt(p,s,d),"review",work,images)
                            atomic_json(work/"review.json",review)
                            proof={"fingerprint":fingerprint,"checked_at":timestamp()}; atomic_json(proof_path,proof)
                        if review_passed(review):
                            record=approve(root,p,s,d,review,proof,topic=items[active].get("topic") or "other",
                                           model=configuration().get("model","Codex default"),generated_at=meta["generated_at"])
                            update(store,active,"approved",error=None,retry_at=None,source_sha=s["sha256"])
                            report["created"]+=1; progress(f"Đã duyệt, đưa vào kho: {record['summary']['title']}",flush=True)
                            if after_approval:
                                try: after_approval()
                                except (RuntimeError,OSError) as exc:
                                    store.set_state("repository:last_error",str(exc))
                            break
                        errors=review.get("issues") or ["Chưa vượt kiểm tra nguồn"]
                    attempts=store.conn.execute("SELECT repair_count FROM editorial_items WHERE doi=?",(active,)).fetchone()[0]
                    if attempts>=MAX_REPAIRS:
                        update(store,active,"needs_attention",error=json.dumps(errors,ensure_ascii=False))
                        report["held"].append({"doi":active,"reason":"review"}); break
                    update(store,active,"repairing",error=json.dumps(errors,ensure_ascii=False))
                    progress(f"Sửa từng đoạn: {active} ({attempts+1}/{MAX_REPAIRS})",flush=True)
                    edits=call(repair_prompt(p,s,d,errors),"repair",work,images)
                    update(store,active,"repairing",repair_count=attempts+1)
                    atomic_json(work/f"draft-before-repair-{attempts+1}.json",d)
                    atomic_json(work/f"repair-{attempts+1}.json",edits)
                    try: changed=apply_repairs(d,edits)
                    except ValueError as exc:
                        update(store,active,"needs_attention",error=str(exc)); break
                    if changed==d:
                        update(store,active,"needs_attention",error="Lượt sửa không thay đổi nội dung"); break
                    d=changed; atomic_json(draft_path,d)
                heartbeat(store,root,report,stage="between_articles")
            else:
                report["status"]="checkpoint"
        except CodexQuotaExceeded as exc:
            retry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat().replace("+00:00","Z")
            store.set_state("producer:retry_at",retry); store.set_state("producer:wait_reason","waiting_quota")
            report.update(status="waiting_quota",error=str(exc),next_retry_at=retry)
            if active: update(store,active,"waiting_quota",retry_at=retry,error=str(exc))
        except CodexAuthenticationRequired as exc:
            retry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat().replace("+00:00","Z")
            store.set_state("producer:retry_at",retry); store.set_state("producer:wait_reason","waiting_auth")
            report.update(status="waiting_auth",error=str(exc),next_retry_at=retry)
            if active: update(store,active,"waiting_auth",retry_at=retry,error=str(exc))
        except CodexUnavailable as exc:
            retry=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat().replace("+00:00","Z")
            store.set_state("producer:retry_at",retry); store.set_state("producer:wait_reason","waiting_codex")
            report.update(status="waiting_codex",error=str(exc),next_retry_at=retry)
            if active: update(store,active,"waiting_codex",retry_at=retry,error=str(exc))
        except BudgetExpired:
            report["status"]="checkpoint"
        except Exception as exc:
            store.set_state("producer:last_exception",{"type":type(exc).__name__,"message":str(exc)})
            report.update(status="needs_attention",error="editorial_pipeline_error")
            if active: update(store,active,"needs_attention",error=str(exc))
        finally:
            report["finished_at"]=timestamp(); heartbeat(store,root,report,stage="idle")
    return report
