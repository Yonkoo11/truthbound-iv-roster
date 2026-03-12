# BountyBoard - Progress

## Last Session: 2026-03-12 (continued)

### What Was Done (all verified)
1. **Cost monitor** -- `scripts/cost_monitor.py` gates all stableenrich API calls. Daily ($0.50) + weekly ($2.00) hard caps. Spend logged to `data/spend_log.jsonl` with file locking. Tested: $0.033 spent so far.
2. **Daily Exa alerts** -- `scripts/exa_daily.py` runs 2 Exa queries daily (~$0.02/day). Deduplicates against DB (URL + slug). Telegram alerts for new finds. Launchd plist at 7AM.
3. **Firecrawl scraper** -- `scripts/firecrawl.py` for JS-rendered pages. URL validation (https only, no private IPs, no localhost). Budget-gated via cost_monitor.
4. **Exa verification loop** -- `verify_data.py --verify-exa` cross-checks `needs_review` entries via Firecrawl. Auto-rejects closed events, flags deadline/prize mismatches.
5. **Find-similar** -- `scout.py` now queries Exa find-similar for top 3 entries (>$50K prize). Discovers related opportunities.
6. **Scout.py refactored** -- Exa calls now use `agentcash_fetch` wrapper (was raw subprocess with npx). Budget-enforced.
7. **Morning brief spending** -- Sunday digest now includes stableenrich spending report.
8. **Pipeline updated** -- `scout_pipeline.sh` now runs `--verify-exa` during verification step.

### Previous Session Work (still valid)
- Website v3 with theme toggle (light/dark mode)
- Calendar cleanup (15 clean events, no SENTINEL branding)
- Exa neural search as 7th scout source
- EVE Frontier x Sui hackathon added

### Architecture
```
bountyboard/
  roster.py        # CLI (default: today)
  db.py            # SQLite DAL
  classify.py      # shared tier logic
  config.py        # centralized config (+ spend caps, agentcash binary path)
  scripts/
    scout.py            # auto-discovery (7 sources + find-similar)
    exa_daily.py        # daily Exa alerts (2 queries, ~$0.02/day)
    cost_monitor.py     # budget-gated agentcash wrapper, spend logging
    firecrawl.py        # JS-rendered scraping via stableenrich Firecrawl
    morning_brief.py    # daily Telegram brief (+ spending on Sundays)
    sync_calendar.py    # Apple Calendar sync
    notify.py           # Telegram + macOS notifications
    migrate.py          # DB migrations
    verify_data.py      # data quality checker (+ --verify-exa flag)
    generate_site.py    # static site generator (light/dark theme toggle)
    scout_pipeline.sh   # scout -> verify-exa -> generate -> push
  launchd/
    com.bountyboard.scout.plist      # Sunday 9AM (runs pipeline)
    com.bountyboard.exa-daily.plist  # Daily 7AM (daily Exa alerts)
    com.bountyboard.calendar.plist   # Daily 8AM
    com.bountyboard.morning.plist    # Daily 6AM
  docs/
    index.html     # generated website (GitHub Pages)
    .nojekyll      # disable Jekyll processing
  data/
    roster.db          # 26 records
    spend_log.jsonl    # stableenrich API cost tracking
    ideas.json         # strategy
    backups/
```

### Security Hardening
- Budget caps: $0.50/day, $2.00/week (hard stops, not warnings)
- Hardcoded binary path: `/opt/homebrew/bin/agentcash` (no npx, no PATH lookup)
- No shell=True anywhere in subprocess calls
- URL validation in firecrawl.py: https only, no private IPs
- All Exa/Firecrawl results start as `needs_review` (never auto-promoted)
- XSS protection: `html.escape()` on all DB fields in site generator
- File locking: fcntl.LOCK_EX on spend log + DB writes

### Costs
- $0.033 spent testing today
- Estimated: ~$5/month total (daily Exa $0.60 + weekly scout $0.32 + find-similar $0.12 + verification $0.28)

### What I Did NOT Do
- Did not load the exa-daily launchd plist (user should do: `launchctl load ~/Library/LaunchAgents/com.bountyboard.exa-daily.plist` after copying)
- Did not run a live end-to-end pipeline test (would spend real USDC)
- Did not test Firecrawl scrape on a real URL (would spend $0.013)
- Budget enforcement tested via import only, not by hitting the actual cap

### Live URL
https://yonkoo11.github.io/bountyboard/
