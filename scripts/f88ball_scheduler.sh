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
#
# Leave this OFF and let scripts/f88ball_uploader.sh do the publishing. That is
# not caution, it is ordering: this flag uploads each video the moment it is
# produced, which is GENERATION order. A Friday match that finishes generating
# after a Sunday one would publish after it, and a round's recap could go out
# ahead of the matches it recaps. The uploader drains a queue sorted by when
# each match was PLAYED, and it also handles the YouTube daily quota of roughly
# six uploads in one place instead of failing mid-run here.
#
#   "no"  -> generate only; the .mp4 lands in profiles/<id>/output/videos/
#            and the uploader picks it up on its next pass
#   "yes" -> upload immediately, in generation order, at YOUTUBE_PRIVACY
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
  echo "[scheduler] uploads disabled here — publishing is the uploader's job."
  echo "[scheduler] see: bash scripts/f88ball_uploader_ctl.sh status"
fi

exec uv run python main.py "${ARGS[@]}"
