"""Use the installed, ChatGPT-authenticated Codex CLI; never API billing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
import uuid

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


class CodexUnavailable(RuntimeError):
    pass


class CodexQuotaExceeded(CodexUnavailable):
    pass


def configuration() -> dict:
    config_file = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    try:
        config = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    return {k: config[k] for k in ("model", "model_reasoning_effort") if config.get(k)}


def authenticated_cli() -> str:
    executable = shutil.which("codex") or shutil.which("codex.exe")
    if not executable and os.name == "nt":
        # The desktop app injects its bundled CLI into this chat's PATH. A scheduled
        # task has a fresh PATH; find the same installation without copying auth.
        binary_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "OpenAI" / "Codex" / "bin"
        installed = sorted(binary_root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        if installed:
            executable = str(installed[0])
    if not executable:
        raise CodexUnavailable("Chưa tìm thấy Codex CLI trong PATH.")
    result = subprocess.run([executable, "login", "status"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    status = (result.stdout + result.stderr).lower()
    if result.returncode or "chatgpt" not in status or "api key" in status:
        raise CodexUnavailable("Codex cần đăng nhập bằng ChatGPT; ứng dụng không dùng API key.")
    return executable


def run_structured(prompt: str, schema_name: str, work_dir: Path,
                   images: list[str] | None = None, timeout: int = 1200) -> dict:
    executable = authenticated_cli()
    schema_path = ROOT / "pipeline" / "schemas" / f"{schema_name}.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    work_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{schema_name}-{uuid.uuid4().hex[:12]}"
    output = work_dir / f"{run_id}.json"
    event_log = work_dir / f"{run_id}.events.jsonl"
    error_log = work_dir / f"{run_id}.stderr.log"
    config = configuration()
    args = [executable, "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only",
            "--skip-git-repo-check", "--color", "never", "--json", "--output-schema", str(schema_path),
            "--output-last-message", str(output), "-C", str(work_dir),
            "-c", 'forced_login_method="chatgpt"', "-c", 'web_search="disabled"']
    if config.get("model"):
        args += ["--model", config["model"]]
    if config.get("model_reasoning_effort"):
        args += ["-c", f'model_reasoning_effort="{config["model_reasoning_effort"]}"']
    for path in (images or [])[:3]:
        if Path(path).is_file():
            args += ["--image", str(Path(path).resolve())]
    args += ["-"]
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    # No shell interpolation, no credential copying, no browser/server-exposed runner.
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with event_log.open("w", encoding="utf-8") as events, error_log.open("w", encoding="utf-8") as errors:
        try:
            proc = subprocess.run(args, input=prompt, stdout=events, stderr=errors,
                                  text=True, encoding="utf-8", env=env, timeout=timeout,
                                  creationflags=flags)
        except subprocess.TimeoutExpired as exc:
            raise CodexUnavailable("Phiên Codex quá thời gian; giữ trạng thái để chạy lại.") from exc
    failure = error_log.read_text(encoding="utf-8", errors="replace")[-18000:]
    failure += event_log.read_text(encoding="utf-8", errors="replace")[-18000:]
    if proc.returncode or not output.exists():
        if any(term in failure.lower() for term in ("usage limit", "rate limit", "quota", "try again at", "limit exceeded")):
            raise CodexQuotaExceeded("Đã chạm hạn mức Codex; sẽ thử lại ở phiên kế tiếp.")
        raise CodexUnavailable(f"Codex không hoàn tất (exit {proc.returncode}); xem nhật ký cục bộ {run_id}.")
    try:
        data = json.loads(output.read_text(encoding="utf-8-sig"))
        jsonschema.validate(data, schema)
    except (ValueError, jsonschema.ValidationError) as exc:
        raise CodexUnavailable(f"Codex trả kết quả không đúng schema: {schema_name}.") from exc
    return data
