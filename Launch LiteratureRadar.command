#!/bin/zsh
set -u
unsetopt BG_NICE 2>/dev/null

PROJECT_DIR="${0:A:h}"
BUILD_SCRIPT="$PROJECT_DIR/Scripts/build_app_bundle.sh"
APP_BUNDLE="$PROJECT_DIR/dist/LiteratureRadar.app"
APP_BIN="$APP_BUNDLE/Contents/MacOS/LiteratureRadar"
LOG_DIR="$HOME/Library/Logs/LiteratureRadar"
LOG_FILE="$LOG_DIR/launcher.log"

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"

/bin/mkdir -p "$LOG_DIR"

if /usr/bin/pgrep -x "LiteratureRadar" >/dev/null 2>&1; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] LiteratureRadar is already running." >> "$LOG_FILE"
    /usr/bin/open "$APP_BUNDLE" >/dev/null 2>&1
    exit 0
fi

if ! cd "$PROJECT_DIR"; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Project directory not found: $PROJECT_DIR" >> "$LOG_FILE"
    /usr/bin/osascript -e 'display alert "LiteratureRadar 启动失败" message "找不到项目目录。"' >/dev/null 2>&1
    exit 1
fi

if [ ! -x "$BUILD_SCRIPT" ]; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Build script not found: $BUILD_SCRIPT" >> "$LOG_FILE"
    /usr/bin/osascript -e 'display alert "LiteratureRadar 启动失败" message "找不到打包脚本。"' >/dev/null 2>&1
    exit 1
fi

NEEDS_BUILD=0
if [ ! -x "$APP_BIN" ]; then
    NEEDS_BUILD=1
elif [ -n "$(/usr/bin/find "$PROJECT_DIR/Package.swift" "$PROJECT_DIR/Sources" "$BUILD_SCRIPT" -type f -newer "$APP_BIN" -print -quit 2>/dev/null)" ]; then
    NEEDS_BUILD=1
fi

if [ "$NEEDS_BUILD" -eq 1 ]; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Building LiteratureRadar.app..." >> "$LOG_FILE"
    if ! "$BUILD_SCRIPT" >> "$LOG_FILE" 2>&1; then
        echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] app bundle build failed." >> "$LOG_FILE"
        /usr/bin/osascript -e 'display alert "LiteratureRadar 编译失败" message "请查看 ~/Library/Logs/LiteratureRadar/launcher.log。"' >/dev/null 2>&1
        exit 1
    fi
fi

echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Launching LiteratureRadar..." >> "$LOG_FILE"
if ! /usr/bin/open "$APP_BUNDLE" >> "$LOG_FILE" 2>&1; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] open failed." >> "$LOG_FILE"
    /usr/bin/osascript -e 'display alert "LiteratureRadar 启动失败" message "请查看 ~/Library/Logs/LiteratureRadar/launcher.log。"' >/dev/null 2>&1
    exit 1
fi
exit 0
