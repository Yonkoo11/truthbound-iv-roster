# TRUTHBOUND IV — Opportunity Roster

A personal CLI + dashboard for tracking hackathons, grants, and bounties. Automatically discovers new opportunities, syncs deadlines to Apple Calendar, and sends a daily morning briefing via Telegram.

---

## Requirements

- macOS (Calendar sync and notifications use osascript)
- Python 3.9+
- Apple Calendar app

---

## Install

```bash
git clone <repo-url>
cd truthbound-iv-roster

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## First Run

Seed the database (only needed once):

```bash
python scripts/migrate.py
```

Verify it worked:

```bash
python roster.py
```

---

## Telegram Setup (optional but recommended)

1. Open Telegram, search `@BotFather`, send `/newbot` — copy the token
2. Send your bot any message, then open:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Find `"chat":{"id":...}` — that's your chat ID
3. Copy the env file and fill in your values:

```bash
cp .env.example .env
# edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

4. Test it:

```bash
python scripts/notify.py info "hello"
```

---

## Automate (cron)

Installs 3 cron jobs:
- **6AM daily** — morning briefing (urgent deadlines + new discoveries)
- **8AM daily** — sync deadlines to Apple Calendar
- **9AM Sundays** — scout for new opportunities across 6 sources

```bash
bash scripts/setup_cron.sh
```

Verify:

```bash
crontab -l
```

---

## Commands

```
python roster.py                  Weekly focus report (default)
python roster.py today            Due this week
python roster.py list             All active opportunities
python roster.py list must        Must-Do tier only
python roster.py search <query>   Full-text search
python roster.py ideas            Winning ideas for Must-Do events
python roster.py sprint           Sprint plan + build order
python roster.py review           Triage auto-discovered items
python roster.py approve <id>     Approve a scouted item
python roster.py reject <id>      Reject a scouted item
python roster.py bulk-reject      Reject multiple at once
python roster.py add              Add opportunity manually
python roster.py add-url <url>    Add from URL (auto-scrapes title/deadline)
python roster.py edit <id>        Edit an existing entry
python roster.py done <id>        Mark as submitted
python roster.py outcome <id>     Record win/loss result
python roster.py stats            Win rate analytics by source
python roster.py export           Export all to data/export.csv
python roster.py undo             Undo last field change
python roster.py health           System health status
```

---

## Web Dashboard

```bash
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501` — 6 tabs: Overview, Ideas, Sprint, All Active, Needs Review, and a timeline chart.

---

## Manual Scout

```bash
python scripts/scout.py              # all sources
python scripts/scout.py --dry-run    # preview, no writes
python scripts/scout.py --source devpost  # single source
```

Sources: ETHGlobal, Devpost, DoraHacks, Gitcoin, Solana Foundation, Twitter/X signals.

---

## Calendar Sync

```bash
python scripts/sync_calendar.py           # sync all unsynced deadlines
python scripts/sync_calendar.py --dry-run # preview only
python scripts/sync_calendar.py --force   # re-sync everything
```

Each event gets 3 reminders: 7 days, 3 days, and 1 day before deadline.

---

## Data

| Path | Contents |
|---|---|
| `data/roster.db` | SQLite database (source of truth) |
| `data/backups/YYYY-MM-DD.json` | Daily versioned backups |
| `data/audit.jsonl` | Audit log of every field change |
| `data/scout_candidates.json` | Low-score items pending review |
| `logs/` | Cron logs per run |

---

## Health Check

```bash
python roster.py health
```

Shows: last scout time, last calendar sync, DB counts by status, backup age, per-source result counts.
