"""
notify.py — Unified notification dispatcher.

Channels: Telegram bot + macOS native notification + JSON log.
All channels are attempted independently; failure in one doesn't block others.

Usage (from other scripts):
    from scripts.notify import send
    send("Scout complete", "Found 3 new opportunities", level="info")
    send("Calendar sync failed", "osascript error: ...", level="error")

Requires in .env (or environment):
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
"""

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR  = Path(__file__).parent.parent
LOG_FILE  = REPO_DIR / "logs" / "notifications.jsonl"

# Load .env if present (without requiring python-dotenv)
_env_file = REPO_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

LEVEL_EMOJI = {"info": "✅", "warning": "🟡", "error": "🔴"}


def _telegram(title: str, body: str, level: str) -> bool:
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    emoji = LEVEL_EMOJI.get(level, "ℹ️")
    text  = f"{emoji} *{title}*\n{body}"

    try:
        import urllib.request
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _macos(title: str, body: str) -> bool:
    if platform.system() != "Darwin":
        return False
    try:
        script = f'display notification "{_esc(body)}" with title "{_esc(title)}"'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _log(title: str, body: str, level: str) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "ts":    datetime.now(timezone.utc).isoformat(),
        "level": level,
        "title": title,
        "body":  body,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def send(title: str, body: str, level: str = "info") -> None:
    """
    Send a notification via all configured channels.
    Never raises — all failures are swallowed.
    """
    # Always log first
    try:
        _log(title, body, level)
    except Exception:
        pass

    # macOS notification
    try:
        _macos(title, body)
    except Exception:
        pass

    # Telegram
    try:
        _telegram(title, body, level)
    except Exception:
        pass


# Allow direct invocation:
#   python scripts/notify.py [level] [title] [body]
#   python scripts/notify.py error "Scout failed" "details here"
if __name__ == "__main__":
    args = sys.argv[1:]
    level = args[0] if args and args[0] in ("info", "warning", "error") else "info"
    title = args[1] if len(args) > 1 else "Test notification"
    body  = args[2] if len(args) > 2 else f"notify.py test — level={level}"
    send(title, body, level=level)
    print(f"Sent: [{level}] {title}")
