#!/usr/bin/env bash
# run_scout.sh — Cron wrapper for scout.py
#
# Locking:  mkdir-based (atomic on macOS + Linux, no flock required)
# Logging:  appends to logs/scout_cron.log
# Rotation: deletes log files older than 30 days
# Notify:   calls notify.py on failure (Telegram + macOS)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3 || command -v python)"
LOGS_DIR="$REPO_DIR/logs"
LOCK_DIR="$LOGS_DIR/scout.lock"
LOG="$LOGS_DIR/scout_cron.log"

mkdir -p "$LOGS_DIR"

# Atomic lock via mkdir (POSIX-safe, no flock needed)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scout already running, skipping" >> "$LOG"
    exit 0
fi
trap "rm -rf '$LOCK_DIR'" EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scout starting" >> "$LOG"

cd "$REPO_DIR"
"$PYTHON" scripts/scout.py >> "$LOG" 2>&1
RC=$?

if [ $RC -ne 0 ]; then
    "$PYTHON" scripts/notify.py error "Scout cron failed (exit $RC)" "Check $LOG" 2>/dev/null || true
else
    # Write heartbeat timestamp for health monitoring
    date -u +%Y-%m-%dT%H:%M:%SZ > "$REPO_DIR/data/.heartbeat"
fi

# Rotate: delete log files older than 30 days
find "$LOGS_DIR" -name "scout_*.log" -mtime +30 -delete 2>/dev/null || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scout done (rc=$RC)" >> "$LOG"
exit $RC
