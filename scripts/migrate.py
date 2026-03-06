"""
migrate.py — One-shot migration from opportunities.json → SQLite.

Safe to re-run: uses upsert so existing rows are updated, not duplicated.
Writes backup to data/opportunities.backup.json before doing anything.

Usage:
    python scripts/migrate.py
    python scripts/migrate.py --dry-run
"""

import json
import sys
from pathlib import Path

REPO_DIR  = Path(__file__).parent.parent
JSON_FILE = REPO_DIR / "data" / "opportunities.json"

sys.path.insert(0, str(REPO_DIR))
import db


def main():
    dry_run = "--dry-run" in sys.argv

    if not JSON_FILE.exists():
        print(f"No opportunities.json found at {JSON_FILE}. Nothing to migrate.")
        return

    with open(JSON_FILE) as f:
        opps = json.load(f)

    print(f"Found {len(opps)} opportunities in {JSON_FILE}")

    # Write backup first
    if not dry_run:
        backup_path = db.backup()
        # backup() reads from DB but DB is empty — write from JSON directly
        backup_path.parent.mkdir(exist_ok=True)
        with open(backup_path, "w") as f:
            json.dump(opps, f, indent=2)
        print(f"Backup written to {backup_path}")

    ok = 0
    errors = []
    for opp in opps:
        # Normalize fields that scout.py or manual entry might have set wrong
        # category: default to hackathon if missing/invalid
        if opp.get("category") not in ("hackathon", "grant", "accelerator", "bounty"):
            opp["category"] = "hackathon"

        # status: map old statuses to new enum
        status_map = {
            "active": "active",
            "needs_review": "needs_review",
            "submitted": "submitted",
            "rejected": "rejected",
            "closed": "closed",
            "won": "won",
            "Submitted": "submitted",
            "Won": "won",
            "Closed": "closed",
        }
        opp["status"] = status_map.get(opp.get("status", "active"), "active")

        # Remove fields that don't exist in new schema
        for extra in ("_tier", "_days", "tier", "days_until", "prize_fmt", "deadline_fmt"):
            opp.pop(extra, None)

        # Ensure id is slug-safe
        if not opp.get("id"):
            opp["id"] = opp.get("name", "unknown").lower().replace(" ", "-")[:40]

        if dry_run:
            try:
                db._validate(opp)
                print(f"  [ok] {opp['id']}")
                ok += 1
            except ValueError as e:
                print(f"  [err] {opp.get('id', '?')}: {e}")
                errors.append(str(e))
        else:
            try:
                db.upsert(opp)
                ok += 1
            except ValueError as e:
                print(f"  [warn] Skipped {opp.get('id', '?')}: {e}")
                errors.append(str(e))

    print(f"\n{'[dry-run] ' if dry_run else ''}Migrated: {ok}/{len(opps)}")
    if errors:
        print(f"Skipped {len(errors)} with validation errors:")
        for e in errors:
            print(f"  - {e}")

    if not dry_run:
        counts = db.count()
        print(f"DB status counts: {counts}")
        print(f"\nDB: {db.DB_FILE}")
        print("Migration complete. opportunities.json is now a backup — db.py is the source of truth.")


if __name__ == "__main__":
    main()
