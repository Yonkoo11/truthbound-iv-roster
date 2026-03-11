from __future__ import annotations

"""
morning_brief.py — Daily 6AM briefing for TRUTHBOUND IV.

Sends a concise digest via notify.py (Telegram + macOS):
  - Urgent deadlines (0-3 days)
  - This week (4-7 days)
  - New needs_review items (top 3)
  - Today's focus (highest-priority active opp with angle)
  - Pipeline stats

Sundays: weekly digest with full stats and next week's deadlines.
Quiet days: "All clear" heartbeat instead of silence.

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


def _fmt_prize(opp: dict) -> str:
    p = opp.get("prize_usd", 0) or 0
    if p >= 100_000:
        return f"${p // 1_000}k"
    if p >= 1_000:
        return f"${p // 1_000}k"
    note = opp.get("prize_note", "") or ""
    return note[:20] if note else ""


def _get_deadlines(opps: list, today: date) -> list[tuple[int, dict]]:
    """Return (days_left, opp) for active items with deadlines, sorted by urgency."""
    result = []
    for o in opps:
        if o.get("status") not in ("active", "needs_review"):
            continue
        dl = o.get("deadline")
        if not dl:
            continue
        try:
            dl_date = datetime.strptime(dl, "%Y-%m-%d").date()
            days_left = (dl_date - today).days
            if days_left >= 0:
                result.append((days_left, o))
        except ValueError:
            pass
    result.sort(key=lambda x: x[0])
    return result


def build_brief() -> str:
    """Build the morning brief text. Always returns a message (never None)."""
    today = date.today()
    is_sunday = today.weekday() == 6
    opps = db.get_all()

    deadlines = _get_deadlines(opps, today)
    urgent = [(d, o) for d, o in deadlines if d <= 3]
    this_week = [(d, o) for d, o in deadlines if 4 <= d <= 7]
    next_week = [(d, o) for d, o in deadlines if 8 <= d <= 14]
    review_items = [o for o in opps if o.get("status") == "needs_review"]
    active_count = sum(1 for o in opps if o.get("status") == "active")
    submitted_count = sum(1 for o in opps if o.get("status") == "submitted")
    won_count = sum(1 for o in opps if o.get("status") == "won")

    day_str = today.strftime("%a %b %d")
    lines = [f"TRUTHBOUND ROSTER — {day_str}", ""]

    # Section 1: URGENT (0-3 days)
    if urgent:
        lines.append("🔴 URGENT (0-3 days)")
        for days_left, o in urgent:
            day_label = "TODAY!" if days_left == 0 else f"{days_left}d"
            prize = _fmt_prize(o)
            fit = o.get("theme_fit", 0) or 0
            prize_str = f" — {prize}" if prize else ""
            lines.append(f"  {o['name']} — {day_label}{prize_str} — fit {fit}/10")
        lines.append("")

    # Section 2: THIS WEEK (4-7 days)
    if this_week:
        lines.append("🟡 THIS WEEK (4-7 days)")
        for days_left, o in this_week:
            prize = _fmt_prize(o)
            fit = o.get("theme_fit", 0) or 0
            prize_str = f" — {prize}" if prize else ""
            lines.append(f"  {o['name']} — {days_left}d{prize_str} — fit {fit}/10")
        lines.append("")

    # Section 3: NEEDS REVIEW
    if review_items:
        lines.append(f"🔍 NEEDS REVIEW ({len(review_items)})")
        for o in review_items[:3]:
            prize = _fmt_prize(o)
            source = o.get("source", "manual")
            prize_str = f" — {prize}" if prize else ""
            lines.append(f"  {o['name']}{prize_str} [{source}]")
        if len(review_items) > 3:
            lines.append(f"  ... +{len(review_items) - 3} more")
        lines.append("")

    # Section 4: TODAY'S FOCUS
    sprint_opps = []
    for o in opps:
        if o.get("status") != "active" or (o.get("theme_fit") or 0) < 6:
            continue
        dl = o.get("deadline")
        if dl:
            try:
                if datetime.strptime(dl, "%Y-%m-%d").date() < today:
                    continue
            except ValueError:
                pass
        sprint_opps.append(o)
    if sprint_opps:
        sprint_opps.sort(key=lambda o: (
            o.get("deadline") or "9999",
            -(o.get("theme_fit") or 0)
        ))
        focus = sprint_opps[0]
        angle = focus.get("angle", "")
        lines.append(f"📌 FOCUS: {focus['name']}")
        if angle:
            lines.append(f"  \"{angle[:80]}\"")
        lines.append("")

    # Section 5: Pipeline stats
    total_prize = sum(o.get("prize_usd", 0) or 0 for o in opps if o.get("status") == "active")
    prize_str = f"${total_prize // 1_000}k" if total_prize >= 1_000 else f"${total_prize}"
    lines.append(f"📊 {active_count} active | {submitted_count} submitted | {won_count} won | {prize_str} in scope")

    # Sunday weekly digest: extra stats
    if is_sunday:
        lines.append("")
        lines.append("— WEEKLY DIGEST —")
        if next_week:
            lines.append("Next week's deadlines:")
            for days_left, o in next_week:
                dl = o.get("deadline", "")
                try:
                    dl_fmt = datetime.strptime(dl, "%Y-%m-%d").strftime("%b %d")
                except ValueError:
                    dl_fmt = dl
                lines.append(f"  {o['name']} — {dl_fmt}")
        else:
            lines.append("No deadlines next week.")

        # Win rate
        outcomes = [o for o in opps if o.get("outcome")]
        if outcomes:
            wins = sum(1 for o in outcomes if o.get("outcome") == "won")
            lines.append(f"Win rate: {wins}/{len(outcomes)} ({100 * wins // len(outcomes)}%)")

    # Quiet day: if nothing urgent, still confirm system is alive
    if not urgent and not this_week and not review_items:
        if deadlines:
            next_d, next_o = deadlines[0]
            lines.insert(2, f"✅ All clear — next deadline: {next_o['name']} in {next_d} days")
            lines.insert(3, "")
        else:
            lines.insert(2, "✅ All clear — no upcoming deadlines")
            lines.insert(3, "")

    return "\n".join(lines)


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    brief = build_brief()

    if dry_run:
        print(brief)
        return

    notify("TRUTHBOUND ROSTER", brief, level="info")


if __name__ == "__main__":
    main()
