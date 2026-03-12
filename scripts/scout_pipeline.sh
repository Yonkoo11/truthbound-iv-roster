#!/bin/bash
# scout_pipeline.sh — Full scout pipeline: discover → verify → generate site → push
#
# Called by launchd (com.bountyboard.scout) every Sunday 9AM.

set -euo pipefail

REPO="/Users/yonko/Projects/bountyboard"
PYTHON="/opt/homebrew/bin/python3"
cd "$REPO"

echo "=== Scout Pipeline $(date) ==="

# Step 1: Scout for new opportunities
echo "--- Running scout ---"
$PYTHON scripts/scout.py 2>&1 || echo "Scout had errors (continuing)"

# Step 2: Verify data quality, close expired + cross-check Exa results
echo "--- Verifying data ---"
$PYTHON scripts/verify_data.py --verify-exa 2>&1

# Step 3: Regenerate website
echo "--- Generating site ---"
$PYTHON scripts/generate_site.py 2>&1

# Step 4: Auto-commit and push if site changed
if git diff --quiet docs/index.html 2>/dev/null; then
    echo "--- No site changes ---"
else
    echo "--- Pushing site update ---"
    git add docs/index.html docs/.nojekyll
    git commit -m "auto: update site $(date +%Y-%m-%d)"
    git push origin main 2>&1 || echo "Push failed (will retry next run)"
fi

echo "=== Pipeline complete ==="
