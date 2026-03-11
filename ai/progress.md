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
10. **Website deployed to GitHub Pages** -- https://yonkoo11.github.io/truthbound-iv-roster/
    - `scripts/verify_data.py` -- marks expired as closed, flags missing URLs
    - `scripts/generate_site.py` -- generates `docs/index.html` from SQLite
    - Dark theme, card layout, filter tabs (All/Hackathons/Grants/Accelerators/Bounties), sort by deadline/prize/fit
    - Past & Closed section collapsed by default
    - Only shows links that exist (no broken/empty links shown)
    - Auto-closed 2 expired entries (Chainlink Mar 8, Monolith Mar 9)
11. **Scout pipeline automated** -- `scripts/scout_pipeline.sh` chains scout -> verify -> generate -> auto-commit/push. Launchd agent updated.

### Data Quality (as of 2026-03-11)
- 2 entries missing URLs: mezo-hackathon (unverified event), cortensor (no public bounty page)
- 8 entries missing submission URLs (grants/rolling programs mostly)
- 16 active entries with URLs = website-ready
- 6 past/closed entries in collapsed section

### Architecture
```
truthbound-iv-roster/
  roster.py        # CLI (default: today)
  db.py            # SQLite DAL
  classify.py      # shared tier logic
  config.py        # centralized config
  scripts/
    scout.py            # auto-discovery (6 platforms)
    morning_brief.py    # daily Telegram brief
    sync_calendar.py    # Apple Calendar sync
    notify.py           # Telegram + macOS notifications
    migrate.py          # DB migrations
    verify_data.py      # data quality checker (NEW)
    generate_site.py    # static site generator (NEW)
    scout_pipeline.sh   # scout -> verify -> generate -> push (NEW)
  launchd/
    com.truthbound.scout.plist    # Sunday 9AM (runs pipeline)
    com.truthbound.calendar.plist # Daily 8AM
    com.truthbound.morning.plist  # Daily 6AM
  docs/
    index.html     # generated website (GitHub Pages)
    .nojekyll      # disable Jekyll processing
  data/
    roster.db      # 25 records
    ideas.json     # strategy
    backups/
```

### Live URL
https://yonkoo11.github.io/truthbound-iv-roster/
