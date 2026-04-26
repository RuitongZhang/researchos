#!/bin/zsh
set -e

PROJECT_DIR="/Users/rtzhang/Documents/New project"
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/LiteratureRadar.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

if [ ! -x ".build/debug/LiteratureRadar" ]; then
  swift build >> "$LOG_FILE" 2>&1
fi

".build/debug/LiteratureRadar" >> "$LOG_FILE" 2>&1 &
disown
