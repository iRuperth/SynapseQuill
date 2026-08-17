#!/bin/bash
# f88ball_scheduler.sh — launch the auto-summary scheduler for the profile below.
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
# Which channel to run. The profile picks the competition (laliga_es -> LaLiga
# + Rōnin FC); switch focus by pointing this at another profile under profiles/.
PROFILE="laliga_es"
INTERVAL="120"   # seconds between polls

# Publish to YouTube as each video is produced?
#   "no"  -> generate only; the .mp4 lands in profiles/<id>/output/videos/
#   "yes" -> upload every generated video, with the privacy from .env
#            (YOUTUBE_PRIVACY, currently 'public') — i.e. it publishes to the
#            channel unattended, which cannot be undone from here.
# Deliberately OFF: publishing is a one-way action and should be a decision, not
# a default inherited from a previous season's setup.
UPLOAD="${F88_UPLOAD:-no}"

cd "$PROJECT_DIR"

# uv lives in ~/.local/bin; ensure it is on PATH when launchd runs us.
export PATH="$HOME/.local/bin:$PATH"

# Unbuffered stdout so the log file shows activity live (stdout is a file
# under launchd, which would otherwise block-buffer prints for hours).
export PYTHONUNBUFFERED=1

ARGS=(--profile "$PROFILE" --scheduler --interval "$INTERVAL")
if [ "$UPLOAD" = "yes" ]; then
  ARGS+=(--upload)
  echo "[scheduler] uploads ENABLED — generated videos will be published to YouTube."
else
  echo "[scheduler] uploads disabled — videos are generated locally only."
  echo "[scheduler] to publish, restart with F88_UPLOAD=yes (or set UPLOAD=yes here)."
fi

exec uv run python main.py "${ARGS[@]}"
