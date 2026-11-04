"""Reconcile existing public articles before activating the cloud publisher."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from .daily import atomic_json, timestamp, write_summary
from .inventory import validate_envelope
from .release import SITE, ledger, save_health
from .repository import command, sync_release_state


def bootstrap(store, root: Path, *, client=None):
    target=root/"public/data/releases.json"
    if target.exists():
        return {"status":"already_migrated","published":len(ledger(root)["releases"])}
    own=client is None; client=client or httpx.Client(timeout=40,follow_redirects=True)
    try:
        response=client.get(SITE+"data/catalog.json",headers={"Cache-Control":"no-cache"});response.raise_for_status()
        catalog=response.json(); releases=[]
        local={s["id"]:s for s in store.summaries()}
        live={s["id"]:s for s in catalog["summaries"]}
        if set(local)!=set(live):
            raise ValueError("Bài ở SQLite khác website; cần đối soát trước khi chuyển publisher")
        for key,s in live.items():
            path=root/"content/summaries"/f"{key}.md"
            if not path.is_file() or local[key]["doi"]!=s["doi"]:
                raise ValueError("Thiếu bài công khai hoặc DOI không khớp khi di chuyển")
            response=client.get(SITE+f"bai-viet/{key}/"); response.raise_for_status()
            if s["doi"] not in response.text:
                raise ValueError(f"Trang công khai không xác nhận DOI {s['doi']}")
            releases.append({"id":key,"doi":s["doi"],"summary_date":s["summary_date"],
                "content_hash":hashlib.sha256(path.read_bytes()).hexdigest(),"published_at":None,
                "verified_at":timestamp(),"deployment":"legacy-live-verification",
                "publication_time_precision":"day"})
        atomic_json(target,{"schema_version":1,"releases":releases})
        ledger(root)  # Enforce the historical cap and uniqueness before cutover.
        atomic_json(root/"public/data/release-state.json",{"schema_version":1,"status":"confirmed","ids":[]})
        store.set_state("operations:version",2)
        save_health(root)
        return {"status":"migrated","published":len(releases)}
    finally:
        if own: client.close()


def reconcile_local(store, root: Path, *, fetch=True):
    sync_release_state(root,fetch=fetch)
    existing={s["id"]:s for s in store.summaries()}
    count=0
    for item in ledger(root)["releases"]:
        old=existing.get(item["id"])
        if old and old.get("summary_date")==item["summary_date"]: continue
        path=root/"content/ready"/f"{item['id']}.json"
        if path.exists(): record=json.loads(path.read_text(encoding="utf-8"))
        else:
            result=command(root,"show",f"origin/main:content/ready/{item['id']}.json")
            record=json.loads(result.stdout)
        validate_envelope(record,root,check_assets=False)
        s=record["summary"]
        if record["approval"]["content_hash"]!=item["content_hash"]: raise ValueError("Sai phiên bản bài cloud đã phát hành")
        store.upsert_papers([{"doi":s["doi"],"title":s["paper_title"],"journal":s["journal"],
                              "authors":s["authors"],"published_online":s["published_online"],"first_seen":s["first_seen"]}])
        store.save_summary(dict(s,summary_date=item["summary_date"],published_at=item.get("published_at"),
            content_hash=item["content_hash"],review=record["approval"]["review"],
            draft={"sections":s["sections"]},search_text="\n".join(p["body"] for p in s["sections"])))
        write_summary(root,dict(s,summary_date=item["summary_date"],content_hash=item["content_hash"]),{"sections":s["sections"]})
        count+=1
    store.set_state("repository:ledger_synced_at",timestamp())
    return count
