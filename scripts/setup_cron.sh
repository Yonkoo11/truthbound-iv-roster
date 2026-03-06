#!/usr/bin/env bash
# setup_cron.sh — Install cron jobs for TRUTHBOUND IV automation
#
# Jobs installed:
#   - Scout (Sundays 9AM): find new opportunities
#   - Calendar sync (daily 8AM): sync deadlines to Apple Calendar
#   - Morning brief (daily 6AM): Telegram digest of urgent deadlines
#
# Locking/logging/rotation/notification are handled by the wrapper scripts:
#   scripts/run_scout.sh
#   scripts/run_sync.sh
#   scripts/run_morning.sh
#
# Idempotent: safe to run multiple times.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3 || command -v python)"
CRON_MARKER="TRUTHBOUND-IV"
LOGS_DIR="$REPO_DIR/logs"

if [ -z "${PYTHON:-}" ]; then
    echo "ERROR: python3 not found in PATH."
    exit 1
fi

# Make wrapper scripts executable
chmod +x "$REPO_DIR/scripts/run_scout.sh"
chmod +x "$REPO_DIR/scripts/run_sync.sh"
chmod +x "$REPO_DIR/scripts/run_morning.sh"

# Ensure logs directory exists (cron can't create it)
mkdir -p "$LOGS_DIR"

echo "TRUTHBOUND IV — Cron Setup"
echo "Repo:   $REPO_DIR"
echo "Python: $PYTHON"
echo ""

# Load existing crontab (ignore error if none exists)
EXISTING_CRON="$(crontab -l 2>/dev/null || true)"

# Check if already installed
if echo "$EXISTING_CRON" | grep -q "$CRON_MARKER"; then
    echo "Cron jobs already installed. Current entries:"
    echo "$EXISTING_CRON" | grep "$CRON_MARKER"
    echo ""
    read -p "Reinstall? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Skipped."
        exit 0
    fi
    # Remove existing TRUTHBOUND-IV entries
    EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -v "$CRON_MARKER")"
fi

# Cron entries: call wrapper scripts (they handle lock, log, notify, rotation)
SCOUT_JOB="0 9 * * 0 bash \"$REPO_DIR/scripts/run_scout.sh\"   # $CRON_MARKER"
SYNC_JOB="0 8 * * * bash \"$REPO_DIR/scripts/run_sync.sh\"    # $CRON_MARKER"
MORNING_JOB="0 6 * * * bash \"$REPO_DIR/scripts/run_morning.sh\" # $CRON_MARKER"

# Write new crontab
printf '%s\n%s\n%s\n%s\n' "$EXISTING_CRON" "$SCOUT_JOB" "$SYNC_JOB" "$MORNING_JOB" | crontab -

echo "Installed:"
echo "  [Scout]    Sundays 9AM  -> scripts/run_scout.sh   (mkdir-lock, log rotation, notify on fail)"
echo "  [Calendar] Daily  8AM   -> scripts/run_sync.sh    (mkdir-lock, log rotation, notify on fail)"
echo "  [Morning]  Daily  6AM   -> scripts/run_morning.sh (Telegram + macOS briefing)"
echo ""
echo "Verify with: crontab -l"
echo ""

# Run calendar sync immediately to seed Calendar with any new deadlines
echo "Running initial calendar sync..."
"$PYTHON" "$REPO_DIR/scripts/sync_calendar.py"
echo "Done."
