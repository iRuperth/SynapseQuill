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
PROJECT_DIR="/Users/rup/Documents/DevelopmentLocal/F88tball"
SRC_PLIST="$PROJECT_DIR/scripts/$LABEL.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# Logs live under ~/Library/Logs (NOT ~/Documents): the Documents tree is
# TCC-protected and launchd can be denied opening a log file there, which kills
# the agent at spawn with EX_CONFIG (78) and no output.
LOG="$HOME/Library/Logs/f88ball/scheduler.log"

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
    # Grab the full list first; piping straight into `grep -q` can SIGPIPE
    # launchctl, which under `pipefail` makes the pipe report failure even when
    # the agent IS loaded (false "Not running").
    line="$(launchctl list | grep "$LABEL" || true)"
    if [ -n "$line" ]; then
      echo "🟢 Running:"
      echo "$line"
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
