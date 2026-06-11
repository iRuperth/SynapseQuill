#!/bin/bash
# f88ball_scheduler_ctl.sh — install / start / stop / status the background
# scheduler as a macOS launchd agent. It survives closing the terminal and the
# IDE, and restarts on crash or at login.
#
# Usage:
#   bash scripts/f88ball_scheduler_ctl.sh install   # install + start
#   bash scripts/f88ball_scheduler_ctl.sh stop      # stop (and disable autostart)
#   bash scripts/f88ball_scheduler_ctl.sh start     # start again
#   bash scripts/f88ball_scheduler_ctl.sh status    # is it running?
#   bash scripts/f88ball_scheduler_ctl.sh logs      # tail the log
#   bash scripts/f88ball_scheduler_ctl.sh uninstall # remove completely

set -euo pipefail

LABEL="com.f88ball.scheduler"
PROJECT_DIR="/Users/rup/Documents/DevelopmentLocal/SynapseQuill"
SRC_PLIST="$PROJECT_DIR/scripts/$LABEL.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PROJECT_DIR/profiles/worldcup_es/output/logs/scheduler.log"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$(dirname "$LOG")"
    cp "$SRC_PLIST" "$DEST_PLIST"
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    launchctl load "$DEST_PLIST"
    echo "✅ Installed and started. Runs in the background (even if you close the IDE)."
    echo "   Logs: $LOG"
    ;;
  start)
    launchctl load "$DEST_PLIST" 2>/dev/null || launchctl start "$LABEL"
    echo "▶️  Started."
    ;;
  stop)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    echo "⏹  Stopped (won't start again until you run 'start'/'install')."
    ;;
  status)
    if launchctl list | grep -q "$LABEL"; then
      echo "🟢 Running:"
      launchctl list | grep "$LABEL"
    else
      echo "🔴 Not running."
    fi
    ;;
  logs)
    tail -n 40 -f "$LOG"
    ;;
  uninstall)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    rm -f "$DEST_PLIST"
    echo "🗑  Uninstalled."
    ;;
  *)
    echo "Usage: bash scripts/f88ball_scheduler_ctl.sh {install|start|stop|status|logs|uninstall}"
    exit 1
    ;;
esac
