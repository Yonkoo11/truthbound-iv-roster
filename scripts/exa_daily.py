"""
exa_daily.py — Daily lightweight Exa search for new opportunities.

Runs 2 targeted queries (not 3 like weekly scout) to catch time-sensitive
hackathons that would be missed by the Sunday-only full scout.

Cost: ~$0.02/day = $0.60/month.

Usage:
    python scripts/exa_daily.py            # normal run
    python scripts/exa_daily.py --dry-run  # preview, no DB writes
"""

import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
LOGS_DIR = REPO_DIR / "logs"
TODAY_ISO = date.today().isoformat()

sys.path.insert(0, str(REPO_DIR))

import db
from scripts.cost_monitor import BudgetExceeded, agentcash_fetch
from scripts.notify import send as notify

# ── Logging ──────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"exa_daily_{TODAY_ISO}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("exa_daily")

# ── Queries (2 per day, tighter than weekly scout's 3) ───────────────────────

DAILY_QUERIES = [
    "new blockchain hackathon 2026 deadline this week",
    "new web3 bounty grant launched this week",
]

EXA_URL = "https://stableenrich.dev/api/exa/search"


def _normalize_date(raw: str) -> str | None:
    """Try to parse a date string into YYYY-MM-DD."""
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip().rstrip(","), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _name_slug(name: str) -> str:
    """Normalize name for dedup: lowercase, strip non-alnum, truncate."""
    return re.sub(r"[^a-z0-9]", "", name.lower())[:30]


def _extract_prize(summary: str) -> int:
    """Extract prize amount from summary text. Returns 0 if not found."""
    match = re.search(r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:K|k)", summary)
    if match:
        return int(float(match.group(1).replace(",", "")) * 1000)
    match = re.search(r"\$(\d[\d,]+)", summary)
    if match:
        val = int(match.group(1).replace(",", ""))
        if val >= 1000:
            return val
    return 0


def _extract_deadline(summary: str) -> str | None:
    """Extract deadline date from summary text."""
    patterns = [
        r"deadline[:\s]+(?:is\s+)?(\w+ \d{1,2},?\s*\d{4})",
        r"(?:runs?|running)\s+(?:from\s+)?\w+ \d{1,2}[^,]*?(?:to|through|until)\s+(\w+ \d{1,2},?\s*\d{4})",
        r"(\w+ \d{1,2},?\s*\d{4})\s*(?:deadline|submission)",
    ]
    for pat in patterns:
        m = re.search(pat, summary, re.IGNORECASE)
        if m:
            result = _normalize_date(m.group(1))
            if result:
                return result
    return None


def run(dry_run: bool = False) -> int:
    """Run daily Exa search. Returns count of new entries found."""
    # Load dedup state
    existing_urls = db.get_urls()
    existing_ids = {o["id"] for o in db.get_all()}
    name_slugs: set[str] = set()
    for eid in existing_ids:
        name_slugs.add(eid[:30].strip("-"))

    new_entries: list[dict] = []
    seen_urls: set[str] = set()

    for query in DAILY_QUERIES:
        body = json.dumps({
            "query": query,
            "numResults": 10,  # fewer than weekly (15)
            "startPublishedDate": f"{date.today().year}-01-01",
            "contents": {
                "summary": {
                    "query": "Extract: hackathon name, organizer, deadline date, prize pool, submission URL"
                },
            },
        })

        try:
            data = agentcash_fetch(EXA_URL, body=body, estimated_cost=0.015)
        except BudgetExceeded as e:
            log.warning(f"Budget exceeded, stopping: {e}")
            break
        except Exception as e:
            log.warning(f"Exa query failed: {e}")
            continue

        items = data.get("data", {}).get("results", [])
        cost = data.get("data", {}).get("costDollars", {}).get("total", 0)
        log.info(f"Query '{query[:50]}': {len(items)} results (${cost:.3f})")

        for item in items:
            url = item.get("url", "").strip()
            title = item.get("title", "").strip()
            if not url or not title:
                continue
            if url in seen_urls or url in existing_urls:
                continue
            seen_urls.add(url)

            slug = _name_slug(title)
            if slug and slug in name_slugs:
                continue
            if slug:
                name_slugs.add(slug)

            summary = item.get("summary", "") or ""
            prize_usd = _extract_prize(summary)
            deadline = _extract_deadline(summary)

            # Skip past deadlines
            if deadline and deadline < TODAY_ISO:
                continue

            new_entries.append({
                "url": url,
                "name": title[:100],
                "description": summary[:500],
                "deadline": deadline,
                "prize_usd": prize_usd,
                "prize_note": f"${prize_usd:,}" if prize_usd else "",
            })

    log.info(f"Found {len(new_entries)} new entries")

    if not new_entries:
        return 0

    if dry_run:
        for e in new_entries:
            log.info(f"  [DRY] {e['name']} | {e.get('deadline', 'no deadline')} | {e.get('prize_note', 'no prize')}")
        return len(new_entries)

    # Insert into DB as needs_review
    for entry in new_entries:
        opp_id = re.sub(r"[^a-z0-9-]", "-", entry["name"].lower())[:50].strip("-")
        try:
            db.upsert({
                "id": opp_id,
                "name": entry["name"],
                "category": "hackathon",
                "status": "needs_review",
                "url": entry["url"],
                "deadline": entry.get("deadline"),
                "prize_usd": entry.get("prize_usd", 0),
                "prize_note": entry.get("prize_note", ""),
                "description": entry.get("description", ""),
                "source": "exa_daily",
            })
            log.info(f"Added: {entry['name']}")
        except Exception as e:
            log.error(f"Failed to add {entry['name']}: {e}")

    # Telegram alert
    names = [e["name"] for e in new_entries[:5]]
    body = "\n".join(f"  • {n}" for n in names)
    if len(new_entries) > 5:
        body += f"\n  ... and {len(new_entries) - 5} more"
    notify(
        f"Exa Daily: {len(new_entries)} new",
        body,
        level="info",
    )

    return len(new_entries)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    count = run(dry_run=dry_run)
    print(f"Done. {count} new entries {'(dry run)' if dry_run else 'added'}.")
