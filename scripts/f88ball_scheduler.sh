#!/bin/bash
# f88ball_scheduler.sh — launch the World Cup auto-summary scheduler.
#
# Polls the data source and, as each match finishes, generates its summary and
# (with --upload) uploads it to YouTube. Runs forever; meant to be supervised by
# launchd (see com.f88ball.scheduler.plist) so it survives terminal/IDE close
# and restarts on crash or login.

set -euo pipefail

# Locate the project from this script's own path (scripts/..) so a moved repo
# keeps working without editing hardcoded paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="worldcup_es"
INTERVAL="120"   # seconds between polls

cd "$PROJECT_DIR"

# uv lives in ~/.local/bin; ensure it is on PATH when launchd runs us.
export PATH="$HOME/.local/bin:$PATH"

# Unbuffered stdout so the log file shows activity live (stdout is a file
# under launchd, which would otherwise block-buffer prints for hours).
export PYTHONUNBUFFERED=1

exec uv run python main.py --profile "$PROFILE" --scheduler --interval "$INTERVAL" --upload
