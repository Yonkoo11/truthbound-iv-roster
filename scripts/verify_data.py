from __future__ import annotations

"""
verify_data.py — Data quality checker for TRUTHBOUND IV Roster.

Checks every opportunity for:
  - Expired deadlines (marks as closed)
  - Missing URLs
  - Broken URLs (HEAD request, 5s timeout)
  - Missing submission URLs

Exa verification (--verify-exa):
  - Cross-checks needs_review entries via Firecrawl scraping
  - Auto-rejects entries where source page says "ended" / "closed"
  - Flags deadline/prize mismatches for human review

Usage:
    python scripts/verify_data.py              # check + auto-fix expired
    python scripts/verify_data.py --dry-run    # report only, no DB writes
    python scripts/verify_data.py --check-urls # also HEAD-check all URLs (slow)
    python scripts/verify_data.py --verify-exa # cross-check needs_review via Firecrawl
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR))

import db


def _check_url(url: str, timeout: int = 5) -> tuple[bool, int]:
    """HEAD-check a URL. Returns (ok, status_code)."""
    if not url:
        return False, 0
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "TruthboundRoster/1.0"})
        return resp.status_code < 400, resp.status_code
    except requests.RequestException:
        # Fall back to GET for servers that block HEAD
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True,
                                headers={"User-Agent": "TruthboundRoster/1.0"},
                                stream=True)
            resp.close()
            return resp.status_code < 400, resp.status_code
        except requests.RequestException:
            return False, 0


def verify(dry_run: bool = False, check_urls: bool = False) -> dict:
    """Run all checks. Returns summary dict."""
    today = date.today()
    opps = db.get_all()

    expired = []
    missing_url = []
    missing_sub_url = []
    broken_urls = []
    ready = []

    for o in opps:
        opp_id = o["id"]
        status = o.get("status", "active")

        # Skip already-closed entries
        if status in ("closed", "rejected", "won"):
            continue

        # Check expired deadlines
        dl = o.get("deadline")
        if dl:
            try:
                dl_date = datetime.strptime(dl, "%Y-%m-%d").date()
                if dl_date < today and status in ("active", "needs_review"):
                    expired.append((opp_id, o["name"], dl))
                    if not dry_run:
                        db.update_field(opp_id, "status", "closed")
                    continue
            except ValueError:
                pass

        # Check URLs
        url = o.get("url", "")
        sub_url = o.get("submission_url", "")

        if not url:
            missing_url.append((opp_id, o["name"]))
        if not sub_url:
            missing_sub_url.append((opp_id, o["name"]))

        # HEAD-check URLs if requested
        if check_urls:
            if url:
                ok, code = _check_url(url)
                if not ok:
                    broken_urls.append((opp_id, o["name"], url, code))
            if sub_url:
                ok, code = _check_url(sub_url)
                if not ok:
                    broken_urls.append((opp_id, o["name"], sub_url, code))

        # Count as ready if it has at least a URL
        if url:
            ready.append(opp_id)

    # Print report
    print(f"TRUTHBOUND ROSTER — Data Quality Report ({today})")
    print(f"{'=' * 50}")
    print(f"Total entries: {len(opps)}")
    print()

    if expired:
        action = "WOULD CLOSE" if dry_run else "CLOSED"
        print(f"⏰ EXPIRED ({action}: {len(expired)})")
        for opp_id, name, dl in expired:
            print(f"  {name} — deadline {dl}")
        print()

    if missing_url:
        print(f"❌ MISSING URL ({len(missing_url)})")
        for opp_id, name in missing_url:
            print(f"  {name} [{opp_id}]")
        print()

    if missing_sub_url:
        print(f"⚠️  MISSING SUBMISSION URL ({len(missing_sub_url)})")
        for opp_id, name in missing_sub_url:
            print(f"  {name} [{opp_id}]")
        print()

    if check_urls and broken_urls:
        print(f"🔗 BROKEN URLS ({len(broken_urls)})")
        for opp_id, name, url, code in broken_urls:
            print(f"  {name} — {code} — {url}")
        print()

    print(f"✅ WEBSITE-READY: {len(ready)} entries have URLs")
    print(f"   (entries without URLs won't show 'Details' link)")

    return {
        "total": len(opps),
        "expired": len(expired),
        "missing_url": len(missing_url),
        "missing_sub_url": len(missing_sub_url),
        "broken_urls": len(broken_urls),
        "ready": len(ready),
    }


def verify_exa(dry_run: bool = False) -> dict:
    """Cross-check needs_review entries by scraping their source pages via Firecrawl."""
    from scripts.firecrawl import scrape

    opps = db.get_all()
    needs_review = [o for o in opps if o.get("status") == "needs_review" and o.get("url")]

    if not needs_review:
        print("No needs_review entries with URLs to verify.")
        return {"checked": 0, "rejected": 0, "flagged": 0}

    print(f"\nExa Verification: checking {len(needs_review)} entries via Firecrawl")
    print(f"{'=' * 50}")

    rejected = []
    flagged = []
    checked = 0

    # Keywords indicating an event is over
    closed_keywords = [
        "has ended", "has closed", "is closed", "event ended",
        "submissions closed", "registration closed", "hackathon ended",
        "event is over", "no longer accepting",
    ]

    for o in needs_review:
        opp_id = o["id"]
        name = o["name"]
        url = o["url"]

        print(f"  Checking: {name}...", end=" ", flush=True)

        md = scrape(url, timeout=30)
        if not md:
            print("scrape failed, skipping")
            continue

        checked += 1
        md_lower = md.lower()

        # Check for closed/ended keywords
        is_closed = any(kw in md_lower for kw in closed_keywords)
        if is_closed:
            print("REJECTED (event closed/ended)")
            rejected.append((opp_id, name, "source page indicates event is closed"))
            if not dry_run:
                db.update_field(opp_id, "status", "rejected")
            continue

        # Check deadline consistency (if we have one)
        dl = o.get("deadline")
        if dl:
            try:
                dl_date = datetime.strptime(dl, "%Y-%m-%d").date()
                # Look for the deadline date in various formats on the page
                dl_found = False
                # Check for the date in common formats
                for fmt in [
                    dl_date.strftime("%B %d"),      # "March 31"
                    dl_date.strftime("%b %d"),       # "Mar 31"
                    dl_date.strftime("%m/%d/%Y"),    # "03/31/2026"
                    dl_date.strftime("%Y-%m-%d"),    # "2026-03-31"
                ]:
                    if fmt.lower() in md_lower:
                        dl_found = True
                        break

                if not dl_found:
                    # Check if any nearby date is mentioned (within 3 days)
                    for delta in range(-3, 4):
                        check_date = dl_date + timedelta(days=delta)
                        if check_date.strftime("%B %d").lower() in md_lower:
                            dl_found = True
                            break

                if not dl_found:
                    flagged.append((opp_id, name, f"deadline {dl} not found on source page"))
            except ValueError:
                pass

        # Check prize consistency (if we have one)
        prize = o.get("prize_usd", 0)
        if prize and prize >= 1000:
            # Look for prize amount on page (within 20% tolerance)
            prize_matches = re.findall(r"\$[\d,]+(?:\.?\d*)?(?:\s*[KkMm])?", md)
            prize_found = False
            for pm in prize_matches:
                pm_clean = pm.replace("$", "").replace(",", "").strip()
                multiplier = 1
                if pm_clean.endswith(("K", "k")):
                    multiplier = 1000
                    pm_clean = pm_clean[:-1]
                elif pm_clean.endswith(("M", "m")):
                    multiplier = 1_000_000
                    pm_clean = pm_clean[:-1]
                try:
                    page_prize = float(pm_clean) * multiplier
                    if abs(page_prize - prize) / prize < 0.20:
                        prize_found = True
                        break
                except ValueError:
                    continue

            if not prize_found:
                flagged.append((opp_id, name, f"prize ${prize:,} not confirmed on source page"))

        print("OK")

    # Print results
    if rejected:
        action = "WOULD REJECT" if dry_run else "REJECTED"
        print(f"\n🚫 {action}: {len(rejected)}")
        for opp_id, name, reason in rejected:
            print(f"  {name} — {reason}")

    if flagged:
        print(f"\n⚠️  FLAGGED FOR REVIEW: {len(flagged)}")
        for opp_id, name, reason in flagged:
            print(f"  {name} — {reason}")

    if not rejected and not flagged:
        print(f"\n✅ All {checked} entries verified OK")

    return {"checked": checked, "rejected": len(rejected), "flagged": len(flagged)}


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    check_urls = "--check-urls" in sys.argv
    verify_exa_flag = "--verify-exa" in sys.argv
    verify(dry_run=dry_run, check_urls=check_urls)
    if verify_exa_flag:
        verify_exa(dry_run=dry_run)


if __name__ == "__main__":
    main()
