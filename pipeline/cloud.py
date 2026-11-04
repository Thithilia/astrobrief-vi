"""GitHub Actions orchestration: reserve -> deploy -> verify -> commit ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import httpx

from .daily import atomic_json
from .release import health, ledger, read_json, prepare, materialize, verify_live, confirm, now_utc, TZ
from .repository import command, publish_files


def deployment_timestamp(run_id: str) -> str:
    token=os.environ.get("GITHUB_TOKEN")
    repository=os.environ.get("GITHUB_REPOSITORY","Thithilia/astrobrief-vi")
    if not token or not run_id.isdigit(): raise RuntimeError("Thiếu định danh deployment để đối soát ngày thực tế")
    with httpx.Client(timeout=35,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json"}) as c:
        response=c.get(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs",params={"per_page":100})
        response.raise_for_status()
        matches=[step["completed_at"] for job in response.json()["jobs"] for step in job.get("steps",[])
                 if step.get("name")=="Deploy to GitHub Pages" and step.get("conclusion")=="success" and step.get("completed_at")]
    if not matches: raise RuntimeError("Chưa tìm được thời điểm deployment thành công; giữ chỗ để đối soát")
    return max(matches)


def live_ids(state: dict) -> set:
    from .release import SITE
    try:
        response=httpx.get(SITE+"data/catalog.json",params={"release":state["plan_id"]},timeout=35,follow_redirects=True)
        response.raise_for_status()
        return {s["id"] for s in response.json()["summaries"]
                if s["id"] in state["ids"] and s.get("content_hash")==state["hashes"][s["id"]]}
    except (httpx.HTTPError,KeyError,ValueError):
        raise RuntimeError("Chưa đọc được website để đối soát; giữ nguyên chỗ đang phát hành")


def save_editions(root: Path, value: dict):
    path=root/"public/data/editions.json"
    history=read_json(path,{"schema_version":1,"days":{}})
    counts={}
    for item in ledger(root)["releases"]: counts[item["summary_date"]]=counts.get(item["summary_date"],0)+1
    history["days"][value["date"]]={"published":value["published"],"target":5,"status":value["status"],"checked_at":value["generated_at"]}
    first=datetime.fromisoformat(min(history["days"])).date()
    end=datetime.fromisoformat(value["date"]).date()
    cursor=first
    while cursor<end:
        history["days"].setdefault(cursor.isoformat(),{"published":counts.get(cursor.isoformat(),0),"target":5,"status":"missed","checked_at":value["generated_at"]})
        cursor+=timedelta(days=1)
    for day,entry in history["days"].items():
        entry["published"]=counts.get(day,0)
        if day<value["date"]: entry["status"]="complete" if entry["published"]==5 else "missed"
    atomic_json(path,history)


def persist(root: Path, *, final=False):
    paths=["public/data/release-state.json","public/data/health.json","public/data/editions.json"]
    if final:
        paths+= ["public/data/releases.json","public/data/catalog.json"]
        paths+= [p.relative_to(root).as_posix() for p in (root/"content/summaries").glob("*.md")]
    result=publish_files(root,paths,release=True,message="Confirm astronomy releases" if final else "Record daily release progress")
    command(root,"fetch","origin","main")
    for folder in ("public/data","content/summaries","content/ready","public/figures"):
        if command(root,"ls-tree","origin/main","--",folder).stdout.strip():
            command(root,"checkout","origin/main","--",folder)
    return result


def preflight(root: Path, *, event: str):
    old_health=read_json(root/"public/data/health.json",{})
    state=read_json(root/"public/data/release-state.json",{})
    if state.get("status")=="deploying":
        if verify_live(root,state):
            stamp=deployment_timestamp(str(state.get("workflow_run_id","")))
            confirm(root,state,published_at=stamp,deployment=str(state["workflow_run_id"]),verified=True)
            value=health(root); save_editions(root,value); persist(root,final=True)
            state=read_json(root/"public/data/release-state.json",{})
        elif live_ids(state):
            raise RuntimeError("Deployment đang lan truyền; chưa phát hành một lô khác")
        else:
            current=datetime.now(TZ)
            if current.hour<7 or (current.hour,current.minute)>=(23,30):
                raise RuntimeError("Còn deployment chưa xác định; giữ lại để chạy lại trong cửa sổ phát hành")
            day=current.date().isoformat()
            used=sum(r["summary_date"]==day for r in ledger(root)["releases"])
            ids=state["ids"][:max(0,5-used)]
            if not ids: raise RuntimeError("Ngày đã đủ năm bài nhưng còn chỗ cũ chưa đối soát")
            state.update(date=day,ids=ids,hashes={key:state["hashes"][key] for key in ids},
                         workflow_run_id=os.environ.get("GITHUB_RUN_ID"),prepared_at=now_utc())
            from .inventory import digest
            state["plan_id"]=digest({"date":day,"hashes":state["hashes"]})
            atomic_json(root/"public/data/release-state.json",state)
    if state.get("status")!="deploying":
        state=prepare(root)
        if state.get("ids"):
            state["workflow_run_id"]=os.environ.get("GITHUB_RUN_ID")
            atomic_json(root/"public/data/release-state.json",state)
    value=health(root)
    comparable=("date","published","missing","deploying","approved_available","status")
    changed=any(old_health.get(k)!=value.get(k) for k in comparable)
    changed=changed or old_health.get("producer",{}).get("heartbeat_at")!=value["producer"].get("heartbeat_at")
    old_time=old_health.get("generated_at")
    stale=not old_time or (datetime.now(timezone.utc)-datetime.fromisoformat(old_time.replace("Z","+00:00"))).total_seconds()>7200
    build=event!="schedule" or bool(state.get("ids")) or changed or stale
    if build:
        atomic_json(root/"public/data/health.json",value); save_editions(root,value)
        persist(root)
    return {"build":build,"release":bool(state.get("ids")),"day_status":value["status"],"published":value["published"]}


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("command",choices=["preflight","materialize","confirm"])
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument("--event",default="workflow_dispatch")
    args=p.parse_args(argv);root=args.root.resolve()
    if args.command=="preflight":
        result=preflight(root,event=args.event)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as output:
                for key,value in result.items(): output.write(f"{key}={str(value).lower()}\n")
    elif args.command=="materialize":
        state=read_json(root/"public/data/release-state.json",{});materialize(root,state); result={"materialized":len(state.get("ids",[]))}
    else:
        import time
        state=read_json(root/"public/data/release-state.json",{})
        passed=False
        for attempt in range(12):
            if verify_live(root,state): passed=True; break
            time.sleep(5)
        if not passed: raise RuntimeError("Chưa xác nhận đủ các trang công khai; giữ chỗ để phục hồi")
        stamp=deployment_timestamp(str(state["workflow_run_id"]))
        result=confirm(root,state,published_at=stamp,deployment=str(state["workflow_run_id"]),verified=True)
        value=health(root);save_editions(root,value);persist(root,final=True)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__": raise SystemExit(main())
