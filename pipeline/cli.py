"""Local administrator commands. No web server can execute these commands."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from .store import Store
from .collect import collect_all
from .export import export_catalog

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="AstroBrief Việt — công cụ quản trị tại máy")
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="Thu thập RSS và đối chiếu metadata")
    collect.add_argument("--days", type=int, default=30)
    collect.add_argument("--rss-only", action="store_true")
    collect.add_argument("--publish", action="store_true")
    daily = sub.add_parser("daily", help="Chọn, viết và kiểm tra tối đa 5 summary/ngày")
    daily.add_argument("--limit", type=int, default=5, choices=range(1, 6))
    daily.add_argument("--catch-up", action="store_true")
    daily.add_argument("--publish", action="store_true")
    sub.add_parser("export", help="Xuất catalog công khai từ trạng thái cục bộ")
    publish = sub.add_parser("publish", help="Commit nội dung đã kiểm tra và đẩy lên GitHub")
    publish.add_argument("--bootstrap", action="store_true")
    sub.add_parser("init-github", help="Tạo repo công khai đã chọn bằng đăng nhập GitHub hiện có")
    sub.add_parser("enable-pages", help="Bật GitHub Pages từ Actions")
    sub.add_parser("deployment-status", help="Đọc trạng thái triển khai GitHub Pages")
    sub.add_parser("status", help="Xem tình trạng thu thập và summary tại máy")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    root.joinpath(".local").mkdir(parents=True, exist_ok=True)
    from .daily import process_lock, run_daily, recover_summary_files
    from .publish import (publish as push, initialize_github, enable_pages,
                          deployment_status, PublishError)
    store = Store(root / ".local" / "state.sqlite")
    result = None
    code = 0
    try:
        if root != ROOT and (getattr(args, "publish", False) or args.command in
                             {"publish", "init-github", "enable-pages", "deployment-status"}):
            raise ValueError("Các lệnh GitHub chỉ chạy với thư mục dự án mặc định; --root khác chỉ dùng cho dữ liệu cục bộ.")
        if args.command == "collect":
            with process_lock(root, "collect"):
                result = collect_all(store, days=args.days, reconcile=not args.rss_only)
                recover_summary_files(store, root)
                export_catalog(store, root)
        elif args.command == "daily":
            result = run_daily(store, root, limit=args.limit, catch_up=args.catch_up)
            recover_summary_files(store, root)
            export_catalog(store, root)
        elif args.command == "export":
            recover_summary_files(store, root)
            result = {"catalog": str(export_catalog(store, root))}
        elif args.command == "init-github":
            result = initialize_github()
        elif args.command == "enable-pages":
            result = enable_pages()
        elif args.command == "deployment-status":
            result = deployment_status()
        elif args.command == "publish":
            with process_lock(root, "publish"):
                recover_summary_files(store, root)
                result = push(bootstrap=args.bootstrap)
        elif args.command == "status":
            summaries = store.summaries()
            result = {"papers": len(store.papers()), "summaries": len(summaries),
                      "daily": store.get_state("daily:last_report"),
                      "summary_dates": sorted({s.get("summary_date") for s in summaries})}
        if getattr(args, "publish", False):
            with process_lock(root, "publish"):
                result = {"job": result, "publication": push()}
    except Exception as exc:
        # Exception messages intentionally contain no credential values.
        result = {"status": "error", "type": type(exc).__name__, "message": str(exc)}
        code = 1
    finally:
        store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return code
