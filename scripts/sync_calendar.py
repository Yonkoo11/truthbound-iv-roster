from __future__ import annotations

"""
sync_calendar.py — Apple Calendar sync for TRUTHBOUND IV deadlines.

Fixes vs original:
- calendar_synced only set True when AppleScript actually succeeds
- Deduplication: checks for existing event before creating
- Retry loop for Calendar startup race condition
- --sync-id: sync a single opportunity (used by roster.py add/edit)
- --remove-past: remove Calendar events for expired/rejected opportunities
- Logs every action to logs/calendar_sync.jsonl
- Notifies on failure via notify.py

Usage:
    python scripts/sync_calendar.py            # sync un-synced
    python scripts/sync_calendar.py --force    # re-sync all
    python scripts/sync_calendar.py --dry-run  # preview only
    python scripts/sync_calendar.py --sync-id chainlink-convergence
    python scripts/sync_calendar.py --remove-past
"""

import json
import subprocess
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
SYNC_LOG = REPO_DIR / "logs" / "calendar_sync.jsonl"
CALENDAR = "Work"
PROJECT  = str(REPO_DIR)

sys.path.insert(0, str(REPO_DIR))
import db
from scripts.notify import send as notify


# ── AppleScript helpers ────────────────────────────────────────────────────────

def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _run_applescript(script: str) -> tuple[bool, str]:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    return True, result.stdout.strip()


def _ensure_calendar_running(max_attempts: int = 3) -> bool:
    """Open Calendar and wait for it to be ready, with retries."""
    subprocess.run(["open", "-a", "Calendar"], capture_output=True)
    for _ in range(max_attempts):
        time.sleep(3)
        ok, _ = _run_applescript('tell application "Calendar" to get name of calendars')
        if ok:
            return True
    return False


def _event_exists(title: str) -> bool:
    """Check if a calendar event with this exact title already exists."""
    script = f"""
tell application "Calendar"
    set found to false
    repeat with cal in calendars
        set evts to (every event of cal whose summary is "{_escape(title)}")
        if (count of evts) > 0 then set found to true
    end repeat
    return found
end tell
"""
    ok, result = _run_applescript(script)
    return ok and result.strip().lower() == "true"


def _log_sync(opp_name: str, status: str, message: str = "") -> None:
    SYNC_LOG.parent.mkdir(exist_ok=True)
    entry = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "opp":     opp_name,
        "status":  status,
        "message": message,
    }
    with open(SYNC_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Core sync ─────────────────────────────────────────────────────────────────

def create_calendar_event(opp: dict, dry_run: bool = False) -> bool:
    deadline_str = opp.get("deadline")
    if not deadline_str:
        print(f"  [skip] {opp['name']}: no deadline")
        return False

    try:
        dl = datetime.strptime(deadline_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"  [skip] {opp['name']}: invalid deadline '{deadline_str}'")
        _log_sync(opp["name"], "skip", f"invalid deadline: {deadline_str}")
        return False

    if dl < date.today():
        print(f"  [skip] {opp['name']}: deadline in the past")
        return False

    title = f"DEADLINE: {opp['name']} (SENTINEL)"
    tracks = ", ".join(opp.get("tracks") or [])
    prize  = opp.get("prize_note") or (f"${opp.get('prize_usd', 0):,}" if opp.get("prize_usd") else "")
    angle  = str(opp.get("angle", ""))[:200]
    url    = opp.get("url", "")
    # AppleScript requires "Month D, YYYY" format — ISO "YYYY-MM-DD" parses incorrectly
    start_date = f"{dl.strftime('%B')} {db.fmt_day(dl)}, {dl.year}"

    description = (
        f"Project: TRUTHBOUND IV / SENTINEL\\n"
        f"Path: {PROJECT}\\n"
        f"Tracks: {tracks}\\n"
        f"Prize: {prize}\\n"
        f"Angle: {angle}\\n"
        f"URL: {url}\\n"
        f"Theme fit: {opp.get('theme_fit') or '?'}/10"
    )

    if dry_run:
        print(f"  [dry-run] Would create: {title} on {dl.isoformat()} with 7d/3d/1d reminders")
        return True

    # Check for duplicate before creating
    if _event_exists(title):
        print(f"  [exists] {title} already in Calendar — skipping")
        _log_sync(opp["name"], "exists")
        return True  # Return True so calendar_synced stays True

    # Note: "description" and "allday event" cannot go inside `with properties {}`
    # because AppleScript treats them as reserved words in record literals.
    # Set them individually after creation.
    script = f"""
tell application "Calendar"
    tell calendar "{_escape(CALENDAR)}"
        set newEvent to make new event with properties {{summary: "{_escape(title)}", start date: date "{start_date}", end date: date "{start_date}"}}
        set allday event of newEvent to true
        set description of newEvent to "{_escape(description)}"
        tell newEvent
            make new display alarm with properties {{trigger interval: -10080}}
            make new display alarm with properties {{trigger interval: -4320}}
            make new display alarm with properties {{trigger interval: -1440}}
        end tell
    end tell
end tell
"""

    ok, err = _run_applescript(script)
    if ok:
        print(f"  [ok] {title} → {start_date}")
        _log_sync(opp["name"], "created", start_date)
    else:
        print(f"  [err] {opp['name']}: {err}")
        _log_sync(opp["name"], "error", err)
        notify("Calendar sync failed", f"{opp['name']}: {err}", level="error")

    return ok


def remove_past_events(dry_run: bool = False) -> None:
    """Remove Calendar events for expired/rejected/closed opportunities."""
    opps = db.get_all()
    today = date.today()
    to_remove = []
    for o in opps:
        if o.get("status") in ("rejected", "closed"):
            to_remove.append(o)
        elif o.get("deadline"):
            try:
                if datetime.strptime(o["deadline"], "%Y-%m-%d").date() < today:
                    to_remove.append(o)
            except ValueError:
                pass

    print(f"Found {len(to_remove)} events eligible for removal.")
    for o in to_remove:
        title = f"DEADLINE: {o['name']} (SENTINEL)"
        if dry_run:
            print(f"  [dry-run] Would remove: {title}")
            continue
        script = f"""
tell application "Calendar"
    repeat with cal in calendars
        set evts to (every event of cal whose summary is "{_escape(title)}")
        repeat with evt in evts
            delete evt
        end repeat
    end repeat
end tell
"""
        ok, err = _run_applescript(script)
        if ok:
            print(f"  [removed] {title}")
            _log_sync(o["name"], "removed")
        else:
            print(f"  [err] {o['name']}: {err}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dry_run    = "--dry-run" in sys.argv
    force      = "--force" in sys.argv
    remove_past = "--remove-past" in sys.argv

    # --sync-id <id>
    sync_id = None
    if "--sync-id" in sys.argv:
        idx = sys.argv.index("--sync-id")
        if idx + 1 < len(sys.argv):
            sync_id = sys.argv[idx + 1]

    if remove_past:
        if not dry_run:
            _ensure_calendar_running()
        remove_past_events(dry_run=dry_run)
        return

    today = date.today()
    if sync_id:
        opp = db.get_by_id(sync_id)
        to_sync = [opp] if opp else []
    else:
        all_opps = db.get_all()
        to_sync = []
        for o in all_opps:
            if o.get("status") in ("closed", "won", "rejected"):
                continue
            dl = o.get("deadline")
            if not dl:
                continue  # rolling/no-deadline — can't place on Calendar
            try:
                if datetime.strptime(dl, "%Y-%m-%d").date() < today:
                    continue
            except ValueError:
                continue
            if not force and o.get("calendar_synced"):
                continue
            to_sync.append(o)

    if not to_sync:
        print("Nothing to sync. Use --force to re-sync all.")
        return

    print(f"Syncing {len(to_sync)} opportunities to '{CALENDAR}' calendar...")
    if not dry_run:
        if not _ensure_calendar_running():
            msg = "Calendar app did not start after 3 attempts. Aborting."
            print(f"[error] {msg}")
            notify("Calendar sync failed", msg, level="error")
            sys.exit(1)

    synced = 0
    failed = 0
    for o in to_sync:
        success = create_calendar_event(o, dry_run=dry_run)
        if success:
            if not dry_run:
                db.update_field(o["id"], "calendar_synced", 1)
            synced += 1
        else:
            failed += 1

    if not dry_run:
        summary = f"{synced} synced, {failed} failed"
        print(f"\nDone. {summary}.")
        _log_sync("__summary__", "complete", summary)
        if failed > 0:
            notify("Calendar sync partial failure", f"{failed} events failed to sync", level="warning")
        else:
            notify("Calendar sync complete", f"{synced} events synced to Calendar", level="info")
    else:
        print(f"\nDry run: {synced} would be synced.")


if __name__ == "__main__":
    main()
