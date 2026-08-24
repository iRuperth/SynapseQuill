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

# Uploads per run. 0 means "keep going until YouTube says the quota is spent".
#
# This used to default to 5, reasoning that ~1600 quota units per upload against
# a 10000/day allowance leaves room for about six. That was the DOCUMENTED
# default for a Cloud project, not a measurement of this one, and it throttled
# publishing for no reason — a run stopped at five while the API was still
# happily accepting uploads. The quota is already handled properly one layer
# down: an exhausted allowance ends the run cleanly and the next wake resumes.
# So let the API be the authority on its own limit rather than guessing it here.
LIMIT="${F88_UPLOAD_LIMIT:-0}"

cd "$PROJECT_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
export PYTHONUNBUFFERED=1

echo "[uploader] $(date '+%Y-%m-%d %H:%M:%S') — publishing up to $LIMIT as '$PRIVACY'"
exec uv run python scripts/f88ball_upload_backlog.py \
    --profile "$PROFILE" --privacy "$PRIVACY" --limit "$LIMIT"
