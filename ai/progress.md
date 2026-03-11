# Truthbound Roster - Progress

## Last Session: 2026-03-11

### What Was Done (all verified)
1. **Fixed Python crash** -- `from __future__ import annotations` in 5 files. All imports verified.
2. **Replaced cron with launchd** -- 3 agents loaded, verified via `launchctl list`. Old cron entries removed. Wrapper scripts deleted.
3. **Extracted `classify.py`** + `config.py`. Removed Streamlit + 3 deps. Fixed scout date parser.
4. **Rewrote morning brief** -- 5 sections, Sunday digest, quiet day heartbeat. Focus excludes expired deadlines. **Live Telegram message sent and received.**
5. **CLI improvements** -- default `today`, flag-based quick-add.
6. **Health command updated** -- shows launchd agent status, reads from launchd logs.
7. **Deleted truthbound-iv (SENTINEL)** -- unused hackathon demo.
8. **Scout verified against live sources** -- ETHGlobal (81 entries), Devpost (18 entries) working. DoraHacks in progress when timed out but no errors.
9. **Calendar sync verified** -- dry-run shows 4 events would sync. Live sync requires Calendar app running (normal for 8AM daily run).

### Remaining Known Issues
- Scout's ETHGlobal parser warns on meetup entries being parsed as dates (cosmetic, not functional)
- Backup is 5 days old (will auto-backup on next db write)
- Source health file not yet written (writes on next scout run)
- Launchd agents untested at scheduled fire times (first real test: tomorrow 6AM morning brief)

### Architecture
```
truthbound-iv-roster/
  roster.py        # CLI (default: today)
  db.py            # SQLite DAL
  classify.py      # shared tier logic
  config.py        # centralized config
  scripts/
    scout.py       # auto-discovery (6 platforms)
    morning_brief.py  # daily Telegram brief
    sync_calendar.py  # Apple Calendar sync
    notify.py      # Telegram + macOS notifications
    migrate.py     # DB migrations
  launchd/
    com.truthbound.scout.plist    # Sunday 9AM
    com.truthbound.calendar.plist # Daily 8AM
    com.truthbound.morning.plist  # Daily 6AM
  data/
    roster.db      # 25 records
    ideas.json     # strategy
    backups/
```
