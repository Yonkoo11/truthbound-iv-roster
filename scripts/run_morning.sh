#!/usr/bin/env bash
# run_morning.sh — Cron wrapper for morning_brief.py
#
# Locking:  mkdir-based (no duplicate runs)
# Logging:  appends to logs/morning_cron.log

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3 || command -v python)"
LOGS_DIR="$REPO_DIR/logs"
LOCK_DIR="$LOGS_DIR/morning.lock"
LOG="$LOGS_DIR/morning_cron.log"

mkdir -p "$LOGS_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] morning brief already running, skipping" >> "$LOG"
    exit 0
fi
trap "rm -rf '$LOCK_DIR'" EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] morning brief starting" >> "$LOG"

cd "$REPO_DIR"
"$PYTHON" scripts/morning_brief.py >> "$LOG" 2>&1
RC=$?

if [ $RC -ne 0 ]; then
    "$PYTHON" scripts/notify.py error "Morning brief failed (exit $RC)" "Check $LOG" 2>/dev/null || true
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] morning brief done (rc=$RC)" >> "$LOG"
exit $RC
