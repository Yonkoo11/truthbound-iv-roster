from __future__ import annotations

"""
verify_data.py — Data quality checker for TRUTHBOUND IV Roster.

Checks every opportunity for:
  - Expired deadlines (marks as closed)
  - Missing URLs
  - Broken URLs (HEAD request, 5s timeout)
  - Missing submission URLs

Usage:
    python scripts/verify_data.py              # check + auto-fix expired
    python scripts/verify_data.py --dry-run    # report only, no DB writes
    python scripts/verify_data.py --check-urls # also HEAD-check all URLs (slow)
"""

import sys
from datetime import date, datetime
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


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    check_urls = "--check-urls" in sys.argv
    verify(dry_run=dry_run, check_urls=check_urls)


if __name__ == "__main__":
    main()
