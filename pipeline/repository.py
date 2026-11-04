"""Publish generated files from a temporary checkout of current remote main.

The user's checkout/index and unrelated source edits are never rewritten.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import uuid

from .daily import atomic_json

GENERATED = ("content/ready/", "public/data/", "public/figures/")
RELEASE_ONLY = {"public/data/releases.json", "public/data/release-state.json", "public/data/health.json", "public/data/editions.json"}


def command(root, *args, check=True):
    result=subprocess.run(["git",*args],cwd=root,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
    if check and result.returncode:
        raise RuntimeError(f"Git {args[0]} thất bại: {result.stderr[-700:]}")
    return result


def merge_catalog(remote: dict, incoming: dict, *, release=False) -> dict:
    # Metadata is a union; no older local export can erase remote releases.
    newer=incoming if incoming.get("generated_at","")>=remote.get("generated_at","") else remote
    older=remote if newer is incoming else incoming
    result=dict(newer)
    papers={p["doi"]:p for p in older.get("papers",[])}
    papers.update({p["doi"]:p for p in newer.get("papers",[])})
    summaries={s["id"]:s for s in remote.get("summaries",[])}
    if release: summaries.update({s["id"]:s for s in incoming.get("summaries",[])})
    by_doi={s["doi"]:s for s in summaries.values()}
    for doi,p in papers.items():
        p=dict(p,has_summary=doi in by_doi)
        if doi in by_doi: p.update(summary_id=by_doi[doi]["id"],topic=by_doi[doi].get("topic","other"))
        else: p.pop("summary_id",None)
        papers[doi]=p
    result["papers"]=list(papers.values())
    result["summaries"]=sorted(summaries.values(),key=lambda s:(s["summary_date"],s["id"]),reverse=True)
    return result


def publish_files(root: Path, paths: list[str], *, release=False, message="Update approved astronomy inventory", retries=3,
                  expected_remote="https://github.com/Thithilia/astrobrief-vi.git"):
    root=Path(root).resolve()
    remote=command(root,"remote","get-url","origin").stdout.strip()
    if remote.removesuffix(".git").casefold()!=expected_remote.removesuffix(".git").casefold():
        raise ValueError("origin không phải repository xuất bản đã chọn")
    staged=command(root,"diff","--cached","--name-only").stdout.splitlines()
    if staged and not release:
        raise RuntimeError("Có thay đổi đang staged; giữ nguyên index của người dùng")
    files={}
    for relative in paths:
        safe=(relative.startswith(GENERATED) and relative not in RELEASE_ONLY) or (release and relative.startswith(("public/data/","content/summaries/")))
        if not safe or ".." in Path(relative).parts:
            raise ValueError(f"Đường dẫn không được phép xuất bản: {relative}")
        path=root/relative
        if path.is_file(): files[relative]=path.read_bytes()
    if not files: return {"changed":False}
    command(root,"fetch","origin","main")
    for attempt in range(retries):
        work=root/".local/publication"/uuid.uuid4().hex
        work.parent.mkdir(parents=True,exist_ok=True)
        command(root,"worktree","add","--detach",str(work),"origin/main")
        try:
            for relative,raw in files.items():
                target=work/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if relative=="public/data/catalog.json" and target.exists():
                    value=merge_catalog(json.loads(target.read_text(encoding="utf-8")),json.loads(raw),release=release)
                    atomic_json(target,value)
                elif relative.startswith("content/ready/") and target.exists():
                    if json.loads(target.read_text(encoding="utf-8"))!=json.loads(raw):
                        raise ValueError("Kho remote có phiên bản đã duyệt khác; không ghi đè")
                elif relative=="public/data/producer.json" and target.exists():
                    old=json.loads(target.read_text(encoding="utf-8"));new=json.loads(raw)
                    if new.get("heartbeat_at","")>=old.get("heartbeat_at",""): target.write_bytes(raw)
                else: target.write_bytes(raw)
            command(work,"add","--",*files)
            if not command(work,"diff","--cached","--name-only").stdout.strip():
                return {"changed":False,"commit":command(work,"rev-parse","HEAD").stdout.strip()}
            # Reuse repo identity locally; never copy account credentials.
            if not command(work,"config","user.name",check=False).stdout.strip():
                command(work,"config","user.name","AstroBrief Việt")
            if not command(work,"config","user.email",check=False).stdout.strip():
                command(work,"config","user.email","astrobrief@users.noreply.github.com")
            command(work,"commit","-m",message)
            result=command(work,"push","origin","HEAD:main",check=False)
            if result.returncode==0:
                return {"changed":True,"commit":command(work,"rev-parse","HEAD").stdout.strip()}
            if attempt+1==retries:
                raise RuntimeError("Chưa đẩy được dữ liệu; giữ bản cục bộ và thử ở phiên sau")
            command(root,"fetch","origin","main")
        finally:
            # This UUID checkout is created by this function; never remove root.
            resolved=work.resolve(); parent=(root/".local/publication").resolve()
            if resolved.parent!=parent or resolved==root: raise RuntimeError("Unsafe temporary worktree path")
            command(root,"worktree","remove","--force",str(resolved))
    raise AssertionError("unreachable")


def generated_paths(root: Path):
    result=[]
    for folder in ("content/ready","public/data","public/figures"):
        for path in (root/folder).rglob("*"):
            relative=path.relative_to(root).as_posix()
            allowed_suffix = path.suffix.lower() in ({".png",".jpg",".jpeg",".webp"} if folder=="public/figures" else {".json"})
            if path.is_file() and allowed_suffix and relative not in RELEASE_ONLY: result.append(relative)
    return result


def sync_release_state(root: Path, *, fetch=True):
    """Read cloud authority without moving the user's branch or editing source."""
    root=Path(root)
    if fetch: command(root,"fetch","origin","main")
    for relative in ("public/data/releases.json","public/data/release-state.json"):
        response=command(root,"show",f"origin/main:{relative}",check=False)
        if response.returncode==0:
            atomic_json(root/relative,json.loads(response.stdout))
    return command(root,"rev-parse","origin/main").stdout.strip()
