from __future__ import annotations

"""
classify.py — Tier classification for BountyBoard opportunities.

Single source of truth for Must-Do / Should-Do / May-Do logic.
"""

from datetime import date, datetime


def days_until(deadline_str: str | None) -> int:
    """Days until deadline. Returns 9999 if no deadline."""
    if not deadline_str:
        return 9999
    try:
        return (datetime.strptime(deadline_str, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return 9999


def classify(opp: dict) -> str:
    """Classify an opportunity into a tier."""
    status = opp.get("status", "active")
    if status in ("closed", "submitted", "won"):
        return status.capitalize()
    if status == "needs_review":
        return "Needs-Review"
    days = days_until(opp.get("deadline"))
    if days < 0:
        return "Expired"
    prize = opp.get("prize_usd", 0) or 0
    fit = opp.get("theme_fit", 0) or 0
    cat = opp.get("category", "")
    if days <= 7:
        return "Must-Do"
    if prize >= 50_000 and fit >= 7:
        return "Must-Do"
    if cat == "accelerator" and fit >= 7:
        return "Must-Do"
    if days <= 21 and (prize >= 20_000 or fit >= 5):
        return "Should-Do"
    if prize >= 20_000 and fit >= 5:
        return "Should-Do"
    return "May-Do"


TIER_RANK = {
    "Must-Do": 0, "Should-Do": 1, "May-Do": 2,
    "Needs-Review": 3, "Submitted": 4, "Won": 5, "Closed": 6, "Expired": 7,
}

TIER_ICON = {
    "Must-Do":      ("bold red",     "🔴"),
    "Should-Do":    ("yellow",       "🟡"),
    "May-Do":       ("cyan",         "🔵"),
    "Needs-Review": ("bold magenta", "🔍"),
    "Submitted":    ("bold green",   "✅"),
    "Won":          ("bold yellow",  "🏆"),
    "Closed":       ("dim",          "⬛"),
    "Expired":      ("dim red",      "❌"),
}


def enrich(data: list) -> list:
    """Add _tier and _days to each opportunity dict."""
    for o in data:
        o["_tier"] = classify(o)
        o["_days"] = days_until(o.get("deadline"))
    return data
