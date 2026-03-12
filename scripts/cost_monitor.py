"""
cost_monitor.py — Budget-gated wrapper for stableenrich API calls.

All stableenrich calls go through agentcash_fetch(). This:
  1. Checks daily/weekly spend caps before each call
  2. Logs every call to data/spend_log.jsonl
  3. Provides wallet balance checks with low-balance alerts

Usage (from other scripts):
    from scripts.cost_monitor import agentcash_fetch, check_wallet, get_spending_report
    result = agentcash_fetch("https://stableenrich.dev/api/exa/search", body=payload)
"""

import fcntl
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR))

from config import (
    AGENTCASH_BIN,
    DAILY_SPEND_CAP,
    SPEND_LOG,
    WEEKLY_SPEND_CAP,
)


class BudgetExceeded(Exception):
    """Raised when a spend cap would be exceeded."""


def _read_spend_log() -> list[dict]:
    """Read all entries from spend log."""
    if not SPEND_LOG.exists():
        return []
    entries = []
    for line in SPEND_LOG.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _append_spend_log(entry: dict) -> None:
    """Append a single entry with file lock."""
    SPEND_LOG.parent.mkdir(exist_ok=True)
    with open(SPEND_LOG, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def check_budget() -> dict:
    """Check remaining budget. Returns {daily_spent, weekly_spent, daily_remaining, weekly_remaining}."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    entries = _read_spend_log()
    daily_spent = 0.0
    weekly_spent = 0.0

    for e in entries:
        try:
            ts = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        cost = e.get("cost", 0.0)
        if ts >= day_ago:
            daily_spent += cost
        if ts >= week_ago:
            weekly_spent += cost

    return {
        "daily_spent": round(daily_spent, 4),
        "weekly_spent": round(weekly_spent, 4),
        "daily_remaining": round(DAILY_SPEND_CAP - daily_spent, 4),
        "weekly_remaining": round(WEEKLY_SPEND_CAP - weekly_spent, 4),
    }


def agentcash_fetch(
    url: str,
    body: str | None = None,
    method: str = "POST",
    timeout: int = 60,
    estimated_cost: float = 0.03,
) -> dict:
    """
    Call stableenrich API via agentcash CLI. Budget-gated and logged.

    Args:
        url: Full stableenrich endpoint URL
        body: JSON string payload (optional)
        method: HTTP method (default POST)
        timeout: Subprocess timeout in seconds
        estimated_cost: Pre-check estimate (actual cost logged from response)

    Returns:
        Parsed JSON response dict

    Raises:
        BudgetExceeded: If daily or weekly cap would be exceeded
        RuntimeError: If agentcash call fails
    """
    # Pre-flight budget check
    budget = check_budget()
    if budget["daily_remaining"] < estimated_cost:
        raise BudgetExceeded(
            f"Daily cap reached: ${budget['daily_spent']:.3f} / ${DAILY_SPEND_CAP:.2f}"
        )
    if budget["weekly_remaining"] < estimated_cost:
        raise BudgetExceeded(
            f"Weekly cap reached: ${budget['weekly_spent']:.3f} / ${WEEKLY_SPEND_CAP:.2f}"
        )

    # Build command -- hardcoded binary path, no shell=True
    cmd = [AGENTCASH_BIN, "fetch", url, "-m", method, "--format", "json"]
    if body:
        cmd.extend(["-b", body])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    # Extract cost from response (fall back to estimate if API doesn't report cost)
    actual_cost = 0.0
    response = {}
    if proc.stdout.strip():
        try:
            response = json.loads(proc.stdout)
            actual_cost = (
                response.get("data", {})
                .get("costDollars", {})
                .get("total", 0.0)
            )
        except json.JSONDecodeError:
            pass
    # Some endpoints (e.g. Firecrawl) don't report cost in response JSON
    # but still charge via x402. Use estimated_cost as floor.
    if actual_cost == 0.0 and proc.returncode == 0:
        actual_cost = estimated_cost

    # Log regardless of success/failure
    _append_spend_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "method": method,
        "cost": actual_cost,
        "status": proc.returncode,
        "ok": proc.returncode == 0,
    })

    if proc.returncode != 0:
        raise RuntimeError(f"agentcash failed (rc={proc.returncode}): {proc.stderr[:300]}")

    return response


def get_total_spent() -> float:
    """Total USDC spent across all time from spend log."""
    entries = _read_spend_log()
    return round(sum(e.get("cost", 0.0) for e in entries), 4)


def get_spending_report() -> str:
    """Formatted spending report for morning brief / Sunday digest."""
    budget = check_budget()
    total = get_total_spent()

    lines = ["📊 *Stableenrich Spending*"]
    lines.append(f"  24h: ${budget['daily_spent']:.3f} / ${DAILY_SPEND_CAP:.2f}")
    lines.append(f"  7d:  ${budget['weekly_spent']:.3f} / ${WEEKLY_SPEND_CAP:.2f}")
    lines.append(f"  All-time: ${total:.3f}")

    # Count calls this week
    entries = _read_spend_log()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    week_calls = sum(
        1 for e in entries
        if datetime.fromisoformat(e.get("ts", "2000-01-01")) >= week_ago
    )
    lines.append(f"  API calls (7d): {week_calls}")

    return "\n".join(lines)


if __name__ == "__main__":
    budget = check_budget()
    print(f"Daily:  ${budget['daily_spent']:.3f} spent, ${budget['daily_remaining']:.3f} remaining")
    print(f"Weekly: ${budget['weekly_spent']:.3f} spent, ${budget['weekly_remaining']:.3f} remaining")

    total = get_total_spent()
    print(f"Total:  ${total:.3f} all-time")
