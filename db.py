from __future__ import annotations

"""
db.py — SQLite data access layer for TRUTHBOUND IV Roster.

All reads/writes go through this module.
File locking (fcntl) prevents concurrent write corruption.
"""

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

DB_FILE      = Path(__file__).parent / "data" / "roster.db"
BACKUP_FILE  = Path(__file__).parent / "data" / "opportunities.backup.json"
BACKUPS_DIR  = Path(__file__).parent / "data" / "backups"
LOCK_FILE    = Path(__file__).parent / "data" / ".roster.lock"
AUDIT_FILE   = Path(__file__).parent / "data" / "audit.jsonl"

VALID_CATEGORIES = ("hackathon", "grant", "accelerator", "bounty")
VALID_STATUSES   = ("active", "needs_review", "submitted", "rejected", "closed", "won")
VALID_OUTCOMES   = (None, "won", "runner_up", "not_selected")

DDL = """
CREATE TABLE IF NOT EXISTS opportunities (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT NOT NULL DEFAULT 'hackathon',
    deadline          TEXT,
    start_date        TEXT,
    prize_usd         INTEGER NOT NULL DEFAULT 0,
    prize_note        TEXT NOT NULL DEFAULT '',
    theme_fit         INTEGER,
    status            TEXT NOT NULL DEFAULT 'active',
    tracks            TEXT NOT NULL DEFAULT '[]',
    angle             TEXT NOT NULL DEFAULT '',
    url               TEXT NOT NULL DEFAULT '',
    resubmittable     INTEGER NOT NULL DEFAULT 0,
    notes             TEXT NOT NULL DEFAULT '',
    calendar_synced   INTEGER NOT NULL DEFAULT 0,
    submitted_project TEXT,
    outcome           TEXT,
    prize_won         INTEGER,
    source            TEXT NOT NULL DEFAULT 'manual',
    submission_url    TEXT NOT NULL DEFAULT '',
    github_link       TEXT NOT NULL DEFAULT '',
    deploy_url        TEXT NOT NULL DEFAULT '',
    hours_spent       INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_status   ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_deadline ON opportunities(deadline);
"""


# ── Connection ─────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    # Migrate: add new columns to existing DBs (SQLite has no ADD COLUMN IF NOT EXISTS)
    for col, defn in [
        ("submission_url", "TEXT NOT NULL DEFAULT ''"),
        ("github_link",    "TEXT NOT NULL DEFAULT ''"),
        ("deploy_url",     "TEXT NOT NULL DEFAULT ''"),
        ("hours_spent",    "INTEGER"),
    ]:
        try:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {defn}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


@contextmanager
def _write_lock():
    """Exclusive file lock for all writes. Prevents concurrent corruption."""
    LOCK_FILE.parent.mkdir(exist_ok=True)
    with open(LOCK_FILE, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _write_audit(action: str, opp_id: str, field: str | None = None,
                 old: Any = None, new: Any = None) -> None:
    """Append one structured line to audit.jsonl. Never raises."""
    try:
        AUDIT_FILE.parent.mkdir(exist_ok=True)
        entry = {
            "ts":     datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "id":     opp_id,
        }
        if field is not None:
            entry["field"] = field
            entry["old"]   = old
            entry["new"]   = new
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # audit failure must never crash the main operation


def get_audit_log(limit: int = 20) -> list[dict]:
    """Return last `limit` audit entries, newest first."""
    if not AUDIT_FILE.exists():
        return []
    try:
        lines = AUDIT_FILE.read_text().splitlines()
        entries = []
        for line in reversed(lines):
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            if len(entries) >= limit:
                break
        return entries
    except Exception:
        return []


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Deserialize JSON fields
    if isinstance(d.get("tracks"), str):
        try:
            d["tracks"] = json.loads(d["tracks"])
        except (json.JSONDecodeError, TypeError):
            d["tracks"] = []
    d["resubmittable"] = bool(d.get("resubmittable", 0))
    d["calendar_synced"] = bool(d.get("calendar_synced", 0))
    return d


# ── Validation ─────────────────────────────────────────────────────────────────

def _validate(opp: dict) -> dict:
    """Validate and normalize an opportunity dict. Returns cleaned dict."""
    errors = []

    if not opp.get("id"):
        errors.append("id is required")
    if not opp.get("name"):
        errors.append("name is required")

    cat = opp.get("category", "hackathon")
    if cat not in VALID_CATEGORIES:
        errors.append(f"category must be one of {VALID_CATEGORIES}, got '{cat}'")

    status = opp.get("status", "active")
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {VALID_STATUSES}, got '{status}'")

    outcome = opp.get("outcome")
    if outcome not in VALID_OUTCOMES:
        errors.append(f"outcome must be one of {VALID_OUTCOMES}, got '{outcome}'")

    deadline = opp.get("deadline")
    if deadline:
        try:
            datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            errors.append(f"deadline must be YYYY-MM-DD, got '{deadline}'")

    theme_fit = opp.get("theme_fit")
    if theme_fit is not None:
        try:
            theme_fit = int(theme_fit)
            if not (1 <= theme_fit <= 10):
                errors.append(f"theme_fit must be 1-10, got {theme_fit}")
        except (TypeError, ValueError):
            errors.append(f"theme_fit must be an integer, got '{theme_fit}'")

    prize_usd = opp.get("prize_usd", 0)
    try:
        prize_usd = int(prize_usd)
    except (TypeError, ValueError):
        prize_usd = 0

    if errors:
        raise ValueError(f"Validation errors for '{opp.get('id', '?')}': {'; '.join(errors)}")

    # Normalize
    tracks = opp.get("tracks", [])
    if isinstance(tracks, list):
        tracks_str = json.dumps(tracks)
    else:
        tracks_str = "[]"

    return {
        "id":                str(opp["id"]),
        "name":              str(opp["name"]),
        "category":          cat,
        "deadline":          deadline,
        "start_date":        opp.get("start_date"),
        "prize_usd":         prize_usd,
        "prize_note":        str(opp.get("prize_note", "")),
        "theme_fit":         theme_fit,
        "status":            status,
        "tracks":            tracks_str,
        "angle":             str(opp.get("angle", "")),
        "url":               str(opp.get("url", "")),
        "resubmittable":     1 if opp.get("resubmittable") else 0,
        "notes":             str(opp.get("notes", "")),
        "calendar_synced":   1 if opp.get("calendar_synced") else 0,
        "submitted_project": opp.get("submitted_project"),
        "outcome":           outcome,
        "prize_won":         opp.get("prize_won"),
        "source":            str(opp.get("source", "manual")),
        "submission_url":    str(opp.get("submission_url", "")),
        "github_link":       str(opp.get("github_link", "")),
        "deploy_url":        str(opp.get("deploy_url", "")),
        "hours_spent":       opp.get("hours_spent"),
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def get_all(status: str | None = None) -> list[dict]:
    """Return all opportunities, optionally filtered by status."""
    conn = _connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE status = ? ORDER BY deadline ASC NULLS LAST, prize_usd DESC",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM opportunities ORDER BY deadline ASC NULLS LAST, prize_usd DESC"
        ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_by_id(opp_id: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def search(query: str) -> list[dict]:
    """Full-text search across name, angle, notes, url."""
    pattern = f"%{query}%"
    conn = _connect()
    rows = conn.execute(
        """SELECT * FROM opportunities
           WHERE name LIKE ? OR angle LIKE ? OR notes LIKE ? OR url LIKE ?
           ORDER BY deadline ASC NULLS LAST""",
        (pattern, pattern, pattern, pattern)
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def upsert(opp: dict) -> None:
    """Insert or update an opportunity. Validates schema. Thread-safe."""
    cleaned = _validate(opp)
    with _write_lock():
        conn = _connect()
        existing = conn.execute(
            "SELECT id FROM opportunities WHERE id = ?", (cleaned["id"],)
        ).fetchone()
        if existing:
            cleaned["updated_at"] = datetime.now().isoformat(timespec="seconds")
            fields = [f for f in cleaned if f not in ("id",)]
            set_clause = ", ".join(f"{f} = :{f}" for f in fields)
            cleaned["id"] = cleaned["id"]  # keep in dict for WHERE clause
            conn.execute(f"UPDATE opportunities SET {set_clause} WHERE id = :id", cleaned)
            _write_audit("upsert_update", cleaned["id"])
        else:
            cols = ", ".join(cleaned.keys())
            placeholders = ", ".join(f":{k}" for k in cleaned.keys())
            conn.execute(f"INSERT INTO opportunities ({cols}) VALUES ({placeholders})", cleaned)
            _write_audit("upsert_insert", cleaned["id"])
        conn.commit()
        conn.close()


def update_field(opp_id: str, field: str, value: Any) -> None:
    """Update a single field. Thread-safe."""
    # Validate field name (prevent SQL injection)
    allowed_fields = {
        "name", "category", "deadline", "start_date", "prize_usd", "prize_note",
        "theme_fit", "status", "tracks", "angle", "url", "resubmittable", "notes",
        "calendar_synced", "submitted_project", "outcome", "prize_won", "source",
        "submission_url", "github_link", "deploy_url", "hours_spent",
    }
    if field not in allowed_fields:
        raise ValueError(f"Field '{field}' not updatable")

    with _write_lock():
        conn = _connect()
        # Capture old value for audit log
        row = conn.execute(f"SELECT {field} FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        old_value = row[0] if row else None
        conn.execute(
            f"UPDATE opportunities SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, datetime.now().isoformat(timespec="seconds"), opp_id)
        )
        conn.commit()
        conn.close()
    _write_audit("update_field", opp_id, field=field, old=old_value, new=value)


def count() -> dict[str, int]:
    """Return counts by status."""
    conn = _connect()
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM opportunities GROUP BY status"
    ).fetchall()
    conn.close()
    return {r["status"]: r["n"] for r in rows}


def backup() -> Path:
    """Export all opportunities to a dated JSON backup. Returns path.

    Writes to data/backups/YYYY-MM-DD.json and prunes files older than 30 days.
    Also keeps data/opportunities.backup.json as a convenience alias.
    """
    import subprocess
    rows = get_all()
    # Dated versioned backup
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    dated = BACKUPS_DIR / f"{date.today().isoformat()}.json"
    with open(dated, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    # Convenience alias (overwrites)
    BACKUP_FILE.parent.mkdir(exist_ok=True)
    with open(BACKUP_FILE, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    # Prune backups older than 30 days
    try:
        subprocess.run(
            ["find", str(BACKUPS_DIR), "-name", "*.json", "-mtime", "+30", "-delete"],
            check=False, capture_output=True
        )
    except Exception:
        pass
    return dated


def get_urls() -> set[str]:
    """Return set of all known URLs for deduplication."""
    conn = _connect()
    rows = conn.execute("SELECT url FROM opportunities WHERE url != ''").fetchall()
    conn.close()
    return {r["url"] for r in rows}


def fmt_day(d: date) -> str:
    """Cross-platform day without leading zero (no %-d which crashes on Windows)."""
    return str(d.day)
