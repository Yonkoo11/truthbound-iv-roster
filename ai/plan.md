# Fix Plan — Post-Build Hardening

## Confirmed Bugs (with evidence)

### CRITICAL: `flock` not on macOS
- Test: `shutil.which('flock')` → `None`
- Impact: cron jobs will silently fail when fired — `command not found` exits the subshell,
  scout.py and sync_calendar.py never run, no error notification
- setup_cron.sh will INSTALL fine (just a string), but nothing will execute at cron time

### MEDIUM: scout.py docstring lies about Encode Club
- Line 8: "Encode Club (web scrape)" in docstring
- Encode Club was dropped (no implementation exists in SOURCES dict)
- Misleading to anyone reading the file

### MEDIUM: feedparser in requirements.txt but unused
- No `import feedparser` anywhere in the codebase
- Was removed when switching from RSS to JSON APIs but never cleaned from requirements

### LOW: roster.py top docstring missing approve/reject commands
- Lines 5-22: docstring lists commands but omits `approve <id>` and `reject <id>`
- Both commands ARE implemented (confirmed in roster.py ~line 989-1008)

### NON-BUGS (audit agent false positives — verified):
- DataFrame.get() with empty Series OR: tested, returns correct result
- Tier name "Needs Review" mismatch: `.replace("_", " ").title()` = "Needs Review" matches INACTIVE set
- Exit code check on scout.py (not find): $? is captured before find runs inside bash -c

---

## Fixes

### Fix 1: Replace flock with mkdir-based locking in setup_cron.sh

Create two wrapper scripts that cron calls, instead of embedding all logic inline:
- `scripts/run_scout.sh` — lock, run, log, notify on failure, rotate logs
- `scripts/run_sync.sh` — same for sync_calendar.py
- `setup_cron.sh` — simplified cron entries that just call the wrapper scripts
- Lock mechanism: `mkdir "$LOCK_DIR" 2>/dev/null || exit 0` (atomic on macOS/Linux)
- Cleanup: `trap "rm -rf '$LOCK_DIR'" EXIT`

### Fix 2: scout.py docstring
- Remove line 8: "  - Encode Club (web scrape)"

### Fix 3: requirements.txt
- Remove: `feedparser>=6.0,<7`

### Fix 4: roster.py docstring
- Add two lines after `python roster.py done <id>`:
  - `python roster.py approve <id>     approve a needs-review opportunity`
  - `python roster.py reject <id>      reject a needs-review opportunity`

### Fix 5: Install cron + verify
- Run `bash scripts/setup_cron.sh`
- Verify: `crontab -l` shows two BountyBoard entries

### Fix 6: Run dashboard visually
- Start streamlit, screenshot to verify tabs render

---

## Order of Operations
1. Fix wrapper scripts + setup_cron.sh (most critical)
2. Fix scout.py, requirements.txt, roster.py (quick text edits)
3. Run bash scripts/setup_cron.sh
4. Verify crontab -l
5. Launch streamlit, take screenshot
