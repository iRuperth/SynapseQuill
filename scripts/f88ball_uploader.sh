#!/bin/bash
# f88ball_uploader.sh — publish generated videos to YouTube, oldest match first.
#
# Deliberately SEPARATE from the generator. The scheduler's own --upload flag
# publishes each video the moment it is produced, which is generation order, not
# match order — a Friday game finished after a Sunday one would go out after it,
# and a round's recap could precede the matches it recaps. Draining a queue on a
# timer instead lets every pending item be sorted by when it was PLAYED.
#
# It also means the daily API quota (about six uploads) is handled in one place:
# the run stops cleanly when the quota is spent and the next run continues.
#
# Supervised by launchd (com.f88ball.uploader.plist), which restarts it on the
# interval below, so it survives logout, reboot and a closed terminal.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="${F88_PROFILE:-laliga_es}"

# Privacy for every upload this runs. 'public' publishes to the channel where
# anyone can find it, and that cannot be undone from here.
PRIVACY="${F88_PRIVACY:-public}"

# Uploads per run. Kept under the ~6 the daily quota allows so a run ends by
# choice rather than by hitting the API ceiling; the remainder goes out next run.
LIMIT="${F88_UPLOAD_LIMIT:-5}"

cd "$PROJECT_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
export PYTHONUNBUFFERED=1

echo "[uploader] $(date '+%Y-%m-%d %H:%M:%S') — publishing up to $LIMIT as '$PRIVACY'"
exec uv run python scripts/f88ball_upload_backlog.py \
    --profile "$PROFILE" --privacy "$PRIVACY" --limit "$LIMIT"
