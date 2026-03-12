from __future__ import annotations

"""
config.py — Centralized configuration for TRUTHBOUND IV Roster.
"""

from pathlib import Path

# Paths
REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "data"
LOGS_DIR = REPO_DIR / "logs"
DB_PATH = DATA_DIR / "roster.db"
IDEAS_FILE = DATA_DIR / "ideas.json"
BACKUP_DIR = DATA_DIR / "backups"
AUDIT_FILE = DATA_DIR / "audit.jsonl"

# Classification thresholds
MUST_DO_DAYS = 7
SHOULD_DO_DAYS = 21
MUST_DO_PRIZE = 50_000
SHOULD_DO_PRIZE = 20_000
MUST_DO_FIT = 7
SHOULD_DO_FIT = 5

# Calendar
CALENDAR_NAME = "Work"

# Scout scoring weights
SCOUT_CORE_WEIGHT = 3    # "ai agent", "zero knowledge proof", etc.
SCOUT_HIGH_WEIGHT = 2    # "zkp", "zkml", "attestation", etc.
SCOUT_MID_WEIGHT = 1     # "blockchain", "web3", etc.
SCOUT_NEG_WEIGHT = -1    # "defi only", "nft only", etc.

# Stableenrich cost controls
DAILY_SPEND_CAP = 0.50       # USD, hard stop per day
WEEKLY_SPEND_CAP = 2.00      # USD, hard stop per week
WALLET_ALERT_THRESHOLD = 1.00  # USD, Telegram warning when balance drops below
SPEND_LOG = DATA_DIR / "spend_log.jsonl"
AGENTCASH_BIN = "/opt/homebrew/bin/agentcash"
