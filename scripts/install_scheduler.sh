#!/bin/bash
# install_scheduler.sh — install / start / stop / status the background scheduler
# as a macOS launchd agent. It survives closing the terminal and the IDE, and
# restarts on crash or at login.
#
# Usage:
#   bash scripts/install_scheduler.sh install   # install + start
#   bash scripts/install_scheduler.sh stop      # stop (and disable autostart)
#   bash scripts/install_scheduler.sh start     # start again
#   bash scripts/install_scheduler.sh status    # is it running?
#   bash scripts/install_scheduler.sh logs      # tail the log
#   bash scripts/install_scheduler.sh uninstall # remove completely

set -euo pipefail

LABEL="com.synapsequill.scheduler"
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
    echo "✅ Instalado y arrancado. Corre en segundo plano (aunque cierres el IDE)."
    echo "   Logs: $LOG"
    ;;
  start)
    launchctl load "$DEST_PLIST" 2>/dev/null || launchctl start "$LABEL"
    echo "▶️  Arrancado."
    ;;
  stop)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    echo "⏹  Detenido (no arrancará hasta que vuelvas a 'start'/'install')."
    ;;
  status)
    if launchctl list | grep -q "$LABEL"; then
      echo "🟢 En ejecución:"
      launchctl list | grep "$LABEL"
    else
      echo "🔴 No está corriendo."
    fi
    ;;
  logs)
    tail -n 40 -f "$LOG"
    ;;
  uninstall)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    rm -f "$DEST_PLIST"
    echo "🗑  Desinstalado."
    ;;
  *)
    echo "Uso: bash scripts/install_scheduler.sh {install|start|stop|status|logs|uninstall}"
    exit 1
    ;;
esac
