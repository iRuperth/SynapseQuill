#!/bin/bash
# f88ball_uploader_ctl.sh — install / start / stop / status the background
# YouTube uploader as a macOS launchd agent. It survives closing the terminal
# and the IDE, and wakes on a timer to publish whatever is pending.
#
# Usage:
#   bash scripts/f88ball_uploader_ctl.sh install   # install + start publishing
#   bash scripts/f88ball_uploader_ctl.sh stop      # stop publishing
#   bash scripts/f88ball_uploader_ctl.sh start     # start again
#   bash scripts/f88ball_uploader_ctl.sh status    # is it installed / when did it last run?
#   bash scripts/f88ball_uploader_ctl.sh pending   # what is queued, in publish order
#   bash scripts/f88ball_uploader_ctl.sh logs      # tail the log
#   bash scripts/f88ball_uploader_ctl.sh uninstall # remove completely
#
# NOTE: `install` starts publishing to the channel immediately, at the privacy
# in F88_PRIVACY (default public). Use `pending` first to see exactly what would
# go out and in what order.

set -euo pipefail

LABEL="com.f88ball.uploader"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_PLIST="$PROJECT_DIR/scripts/$LABEL.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/f88ball/uploader.log"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$(dirname "$LOG")"
    # Render both placeholders: the repo location and the home directory, so the
    # plist never carries a path from whoever generated it.
    sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__HOME__|$HOME|g" \
        "$SRC_PLIST" > "$DEST_PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST_PLIST"
    # Read the cadence out of the plist rather than restating it here, so the
    # two cannot drift apart the way they already did once.
    EVERY="$(/usr/bin/plutil -extract StartInterval raw -o - "$DEST_PLIST" 2>/dev/null || echo "?")"
    echo "Installed and started. Publishes in the background every ${EVERY}s."
    echo "   Logs: $LOG"
    ;;
  start)
    launchctl bootstrap "gui/$(id -u)" "$DEST_PLIST" 2>/dev/null \
      || launchctl kickstart "gui/$(id -u)/$LABEL"
    echo "Started."
    ;;
  stop)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    echo "Stopped. Nothing will be published until you start it again."
    ;;
  status)
    if launchctl list | grep -q "$LABEL"; then
      echo "Installed and loaded:"
      launchctl list | grep "$LABEL"
    else
      echo "Not loaded."
    fi
    [ -f "$LOG" ] && echo "--- last run ---" && tail -n 12 "$LOG"
    ;;
  pending)
    cd "$PROJECT_DIR"
    export PATH="$HOME/.local/bin:$PATH"
    uv run python scripts/f88ball_upload_backlog.py \
        --profile "${F88_PROFILE:-laliga_es}" \
        --privacy "${F88_PRIVACY:-public}" --dry-run
    ;;
  logs)
    tail -f "$LOG"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$DEST_PLIST"
    echo "Uninstalled."
    ;;
  *)
    echo "Usage: $0 {install|start|stop|status|pending|logs|uninstall}" >&2
    exit 1
    ;;
esac
