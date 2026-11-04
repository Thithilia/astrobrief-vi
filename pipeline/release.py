"""Cloud release state machine. No Codex, credentials or local SQLite required."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import httpx

from .daily import atomic_json, write_summary
from .inventory import digest, load_inventory, preview

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SITE = "https://thithilia.github.io/astrobrief-vi/"
TARGET = 5


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def ledger(root: Path) -> dict:
    value = read_json(root / "public/data/releases.json", {"schema_version": 1, "releases": []})
    ids, dois, days = set(), set(), {}
    for item in value["releases"]:
        if item["id"] in ids or item["doi"] in dois:
            raise ValueError("Sổ phát hành có ID/DOI trùng")
        ids.add(item["id"]); dois.add(item["doi"])
        day = item["summary_date"]
        days[day] = days.get(day, 0) + 1
        if days[day] > TARGET:
            raise ValueError("Sổ phát hành vượt năm bài trong một ngày")
    return value


def health(root: Path, now: datetime | None = None) -> dict:
    current = (now or datetime.now(TZ)).astimezone(TZ)
    records = ledger(root)["releases"]
    published = {r["id"] for r in records}
    state = read_json(root / "public/data/release-state.json", {})
    reserved = set(state.get("ids", [])) if state.get("status") == "deploying" else set()
    inventory = load_inventory(root)
    available = len(set(inventory) - published - reserved)
    count = sum(r["summary_date"] == current.date().isoformat() for r in records)
    status = "complete" if count == TARGET else "not_due" if current.hour < 7 else "missed" if (current.hour, current.minute) >= (23, 30) else "running"
    if status == "running":
        status = "waiting_deployment" if reserved else "waiting_inventory" if not available else "running"
    return {"schema_version": 1, "generated_at": now_utc(), "date": current.date().isoformat(),
            "timezone": "Asia/Saigon", "target": TARGET, "published": count, "missing": TARGET-count,
            "deploying": len(reserved), "approved_available": available, "reserve_target": 35,
            "reserve_days": available // TARGET, "reserve_low": available < 10, "status": status,
            "producer": read_json(root / "public/data/producer.json", {})}


def save_health(root, now=None):
    value = health(root, now)
    atomic_json(root / "public/data/health.json", value)
    return value


def prepare(root: Path, now: datetime | None = None) -> dict:
    current = (now or datetime.now(TZ)).astimezone(TZ)
    day = current.date().isoformat()
    history = ledger(root)["releases"]
    inventory = load_inventory(root)
    state_path = root / "public/data/release-state.json"
    state = read_json(state_path, {})
    if state.get("status") == "deploying":
        # Reconcile first. Never choose another batch while a deployment is uncertain.
        return state
    count = sum(r["summary_date"] == day for r in history)
    if count >= TARGET or current.hour < 7 or (current.hour, current.minute) >= (23, 30):
        return {"status": "idle", "date": day, "ids": []}
    used = {r["id"] for r in history}
    choices = [record for key, record in inventory.items() if key not in used]
    choices.sort(key=lambda r: (r["summary"].get("published_online") or "", r["summary"]["generated_at"]), reverse=True)
    chosen, topics = [], set()
    # Prefer diverse topics without excluding an otherwise eligible article.
    while choices and len(chosen) < TARGET-count:
        index = next((i for i,r in enumerate(choices) if r["summary"]["topic"] not in topics), 0)
        record = choices.pop(index); chosen.append(record); topics.add(record["summary"]["topic"])
    if not chosen:
        return {"status": "idle", "date": day, "ids": []}
    hashes = {r["summary"]["id"]: r["approval"]["content_hash"] for r in chosen}
    state = {"schema_version": 1, "status": "deploying", "date": day, "ids": list(hashes),
             "hashes": hashes, "prepared_at": now_utc(), "plan_id": digest({"date": day, "hashes": hashes})}
    atomic_json(state_path, state)
    return state


def materialize(root: Path, state: dict, *, actual_day: str | None = None):
    if not state.get("ids"):
        return
    inventory = load_inventory(root)
    catalog_path = root / "public/data/catalog.json"
    catalog = read_json(catalog_path, {"papers": [], "summaries": [], "journals": []})
    summaries = {s["id"]: s for s in catalog["summaries"]}
    day = actual_day or state["date"]
    for key in state["ids"]:
        record = inventory[key]
        if record["approval"]["content_hash"] != state["hashes"][key]:
            raise ValueError("Nội dung trong chỗ giữ đã thay đổi")
        s = dict(record["summary"], summary_date=day, content_hash=state["hashes"][key])
        write_summary(root, s, {"sections": s["sections"]})
        summaries[key] = preview(record, day)
    catalog["summaries"] = sorted(summaries.values(), key=lambda s:(s["summary_date"],s["id"]), reverse=True)
    by_doi = {s["doi"]:s for s in summaries.values()}
    for p in catalog["papers"]:
        p["has_summary"] = p["doi"] in by_doi
        if p["has_summary"]:
            p["summary_id"] = by_doi[p["doi"]]["id"]
            p["topic"] = by_doi[p["doi"]]["topic"]
    catalog["generated_at"] = now_utc()
    atomic_json(catalog_path, catalog)


def verify_live(root: Path, state: dict, *, client=None, site=SITE) -> bool:
    if not state.get("ids"):
        return True
    own_client = client is None
    client = client or httpx.Client(timeout=35, follow_redirects=True)
    try:
        response = client.get(site + "data/catalog.json", params={"release": state["plan_id"]}, headers={"Cache-Control":"no-cache"})
        response.raise_for_status()
        live = {s["id"]:s for s in response.json()["summaries"]}
        inventory = load_inventory(root)
        for key in state["ids"]:
            record = inventory[key]
            if (key not in live or live[key].get("doi") != record["summary"]["doi"]
                    or live[key].get("content_hash") != state["hashes"][key]):
                return False
            response = client.get(site + f"bai-viet/{key}/", params={"release":state["plan_id"]})
            response.raise_for_status()
            # Exact version marker emitted by the static article route.
            if f'data-content-hash="{state["hashes"][key]}"' not in response.text:
                return False
        return True
    except (httpx.HTTPError, KeyError, ValueError):
        return False
    finally:
        if own_client:
            client.close()


def confirm(root: Path, state: dict, *, published_at: str, deployment: str, verified: bool):
    if not verified:
        raise ValueError("Chưa xác minh nội dung công khai")
    day = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
    value = ledger(root)
    used = {r["id"] for r in value["releases"]}
    new_ids = [key for key in state.get("ids", []) if key not in used]
    if not new_ids:
        return {"confirmed":0,"date":day,"already_confirmed":True}
    if sum(r["summary_date"] == day for r in value["releases"]) + len(new_ids) > TARGET:
        raise ValueError("Deployment sẽ vượt trần ngày thực tế; cần đối soát trước")
    inventory = load_inventory(root)
    materialize(root, state, actual_day=day)
    for key in new_ids:
        value["releases"].append({"id":key, "doi":inventory[key]["summary"]["doi"], "summary_date":day,
            "content_hash":state["hashes"][key], "published_at":published_at, "verified_at":now_utc(),
            "deployment":deployment, "plan_id":state["plan_id"]})
    atomic_json(root / "public/data/releases.json", value)
    atomic_json(root / "public/data/release-state.json", {"schema_version":1,"status":"confirmed",
                "plan_id":state.get("plan_id"), "confirmed_at":now_utc(), "ids":[]})
    save_health(root)
    return {"confirmed":len(new_ids), "date":day}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["prepare","materialize","verify","confirm","health"])
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--published-at"); parser.add_argument("--deployment",default="")
    args=parser.parse_args(argv); root=args.root.resolve()
    if args.command=="prepare":
        result=prepare(root); save_health(root)
    elif args.command=="health": result=save_health(root)
    else:
        state=read_json(root/"public/data/release-state.json",{})
        if args.command=="materialize":
            materialize(root,state); result=state
        else:
            passed=False
            for attempt in range(8):
                passed=verify_live(root,state)
                if passed: break
                time.sleep(5)
            if not passed:
                print(json.dumps({"status":"waiting_deployment","verified":False})); return 2
            if args.command=="verify": result={"verified":True}
            else:
                result=confirm(root,state,published_at=args.published_at or now_utc(),
                               deployment=args.deployment,verified=True)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
