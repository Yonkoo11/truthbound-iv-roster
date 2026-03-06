"""
morning_brief.py — Daily 6AM briefing for TRUTHBOUND IV.

Sends a concise digest via notify.py (Telegram + macOS):
  - Urgent deadlines (<7 days)
  - New needs_review items
  - Today's sprint focus (highest-priority active opportunity)

Usage:
    python scripts/morning_brief.py           # send brief
    python scripts/morning_brief.py --dry-run # print to stdout, no send
"""

import sys
from datetime import date, datetime
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR))

import db
from scripts.notify import send as notify


def build_brief() -> str | None:
    """Build the morning brief text. Returns None if nothing to report."""
    today = date.today()
    opps  = db.get_all()

    # Urgent: active deadlines within 7 days
    urgent = []
    for o in opps:
        if o.get("status") not in ("active", "needs_review"):
            continue
        dl = o.get("deadline")
        if not dl:
            continue
        try:
            dl_date   = datetime.strptime(dl, "%Y-%m-%d").date()
            days_left = (dl_date - today).days
            if 0 <= days_left <= 7:
                urgent.append((days_left, o))
        except ValueError:
            pass
    urgent.sort(key=lambda x: x[0])

    # New needs_review count
    review_items = [o for o in opps if o.get("status") == "needs_review"]

    # Nothing to report — skip (no spam on quiet days)
    if not urgent and not review_items:
        return None

    # Build text
    day_str = today.strftime("%a %b %d")
    lines   = [f"TRUTHBOUND IV — Morning Brief ({day_str})", ""]

    if urgent:
        lines.append("URGENT (deadline <7 days):")
        for days_left, o in urgent:
            prize_str = f" | ${o['prize_usd']:,}" if o.get("prize_usd") else ""
            day_label = "TODAY" if days_left == 0 else f"{days_left}d left"
            lines.append(f"  • {o['name']} — {day_label}{prize_str}")
        lines.append("")

    if review_items:
        lines.append(f"NEW TO REVIEW ({len(review_items)} item{'s' if len(review_items) != 1 else ''}):")
        lines.append("  python roster.py review")
        lines.append("")

    # Sprint focus: highest theme_fit active opp with soonest deadline
    sprint_opps = [
        o for o in opps
        if o.get("status") == "active" and o.get("theme_fit") and (o.get("theme_fit") or 0) >= 6
    ]
    if sprint_opps:
        sprint_opps.sort(key=lambda o: (
            o.get("deadline") or "9999",
            -(o.get("theme_fit") or 0)
        ))
        focus = sprint_opps[0]
        lines.append(f"TODAY'S FOCUS: {focus['name']}")

    return "\n".join(lines)


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    brief   = build_brief()

    if brief is None:
        if dry_run:
            print("Nothing to report today — no brief sent.")
        return

    if dry_run:
        print(brief)
        return

    notify("TRUTHBOUND IV — Morning Brief", brief, level="info")


if __name__ == "__main__":
    main()
