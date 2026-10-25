"""Publish reviewed static content through GitHub; credentials never enter the repo."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import httpx

ROOT = Path(__file__).resolve().parents[1]
OWNER, REPOSITORY = "Thithilia", "astrobrief-vi"
REMOTE = f"https://github.com/{OWNER}/{REPOSITORY}.git"


class PublishError(RuntimeError):
    pass


def git(*args: str, check=True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
    if check and result.returncode:
        raise PublishError(f"Git thất bại: {' '.join(args[:2])}: {result.stderr[-800:]}")
    return result


def github_client() -> httpx.Client:
    # Git Credential Manager handles its existing login. Secret stays in memory.
    result = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                            input="protocol=https\nhost=github.com\nusername=Thithilia\n\n",
                            capture_output=True, text=True, encoding="utf-8", timeout=90)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = values.get("password")
    if result.returncode or not token:
        raise PublishError("Cần đăng nhập GitHub qua Git Credential Manager hoặc gh auth login.")
    return httpx.Client(base_url="https://api.github.com", timeout=40, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "AstroBrief-Viet-local-publisher"})


def initialize_github() -> dict:
    with github_client() as client:
        who = client.get("/user")
        who.raise_for_status()
        if who.json()["login"].casefold() != OWNER.casefold():
            raise PublishError("Tài khoản GitHub hiện tại không phải Thithilia.")
        response = client.get(f"/repos/{OWNER}/{REPOSITORY}")
        if response.status_code == 404:
            response = client.post("/user/repos", json={
                "name": REPOSITORY, "private": False,
                "description": "Theo dõi sáu journal thiên văn và giải thích bài mới bằng tiếng Việt.",
                "has_issues": True, "auto_init": False})
            response.raise_for_status()
        else:
            response.raise_for_status()
            if response.json().get("private"):
                raise PublishError("Repository đã tồn tại ở chế độ riêng; không tự thay đổi quyền truy cập.")
            current_origin = git("remote", "get-url", "origin", check=False)
            if current_origin.returncode and response.json().get("size", 0) > 0:
                raise PublishError("Repository đã có nội dung; không tự ghi đè từ thư mục mới.")
        repo = response.json()
        current = git("remote", "get-url", "origin", check=False)
        if current.returncode:
            git("remote", "add", "origin", REMOTE)
        elif current.stdout.strip().removesuffix(".git").casefold() != REMOTE.removesuffix(".git").casefold():
            raise PublishError("origin đang trỏ đến repository khác.")
        if not git("config", "--local", "user.name", check=False).stdout.strip():
            git("config", "user.name", who.json().get("name") or OWNER)
        if not git("config", "--local", "user.email", check=False).stdout.strip():
            git("config", "user.email", f"{who.json()['id']}+{OWNER}@users.noreply.github.com")
        return {"repository": repo["html_url"], "visibility": "public"}


def enable_pages() -> dict:
    with github_client() as client:
        response = client.get(f"/repos/{OWNER}/{REPOSITORY}/pages")
        if response.status_code == 404:
            response = client.post(f"/repos/{OWNER}/{REPOSITORY}/pages", json={"build_type": "workflow"})
        response.raise_for_status()
        return {"url": response.json().get("html_url"), "status": response.json().get("status")}


def publish(bootstrap: bool = False) -> dict:
    origin = git("remote", "get-url", "origin", check=False)
    if origin.returncode or origin.stdout.strip().removesuffix(".git").casefold() != REMOTE.removesuffix(".git").casefold():
        raise PublishError("Chưa cấu hình đúng repository xuất bản.")
    # A prior unrelated staging area must never be committed by the scheduler.
    staged = git("diff", "--cached", "--name-only").stdout.splitlines()
    allowed = ("content/summaries/", "public/data/", "public/figures/")
    if not bootstrap and any(not p.startswith(allowed) for p in staged):
        raise PublishError("Có thay đổi mã nguồn đang staged; giữ nguyên để người dùng xử lý.")
    if bootstrap:
        git("add", "--all")
    else:
        paths = [p for p in ("content/summaries", "public/data", "public/figures") if (ROOT / p).exists()]
        if paths:
            git("add", "--", *paths)
    if not git("diff", "--cached", "--name-only").stdout.strip():
        # An earlier push may have failed after committing. Always retry a plain push.
        result = git("push", "-u", "origin", "main", check=False)
        if result.returncode:
            raise PublishError("Chưa đẩy được commit lên GitHub; nội dung vẫn được giữ tại máy.")
        return {"changed": False, "url": f"https://{OWNER.lower()}.github.io/{REPOSITORY}/"}
    git("commit", "-m", "Publish AstroBrief Việt" if bootstrap else "Update astronomy papers and reviewed summaries")
    # Never force-push, auto-stash, reset, or overwrite remote edits.
    result = git("push", "-u", "origin", "main", check=False)
    if result.returncode:
        raise PublishError("Git push chưa thành công; giữ commit cục bộ, không ghi đè remote.")
    return {"changed": True, "commit": git("rev-parse", "HEAD").stdout.strip(),
            "url": f"https://{OWNER.lower()}.github.io/{REPOSITORY}/"}


def deployment_status() -> dict:
    with github_client() as client:
        response = client.get(f"/repos/{OWNER}/{REPOSITORY}/actions/runs", params={"per_page": 3})
        response.raise_for_status()
        return {"runs": [{k: run.get(k) for k in ("id", "status", "conclusion", "html_url", "head_sha")}
                         for run in response.json().get("workflow_runs", [])]}
