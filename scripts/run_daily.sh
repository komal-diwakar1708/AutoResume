#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Daily runner for AutomateResume.
# Searches for Product Manager / Associate Product Manager jobs posted in the
# last 24 hours across all configured countries, then regenerates the
# country-grouped HTML report.
#
# Invoked by launchd (see com.automateresume.daily.plist) once per day.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_DIR="/Users/k0d08gu/Documents/AutomateResume"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"

# Pin Playwright's browser location to a stable project-local folder so the
# scheduled run always finds Chromium (default cache paths can be ephemeral).
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_DIR/.pw-browsers"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

echo "=============================================================="
echo "Daily run started: $(date)"
echo "=============================================================="

# --no-check skips the interactive setup prompt; run the full pipeline.
"$PYTHON" main.py --no-check >> "$LOG_DIR/daily_run.log" 2>&1

echo "Daily run finished: $(date)"
