#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
CONFIGURATION="${LITRADAR_CONFIGURATION:-release}"
APP_NAME="LiteratureRadar"
APP_BUNDLE="$PROJECT_DIR/dist/$APP_NAME.app"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
BUNDLE_ID="com.researchos.LiteratureRadar"
VERSION="0.1.0"

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
export CLANG_MODULE_CACHE_PATH="$PROJECT_DIR/.build/clang-module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$PROJECT_DIR/.build/swiftpm-module-cache"

cd "$PROJECT_DIR"
/bin/mkdir -p "$CLANG_MODULE_CACHE_PATH" "$SWIFTPM_MODULECACHE_OVERRIDE"

/usr/bin/swift build -c "$CONFIGURATION"
BUILD_DIR="$(/usr/bin/swift build --show-bin-path -c "$CONFIGURATION" | /usr/bin/tail -n 1)"
EXECUTABLE="$BUILD_DIR/$APP_NAME"
RESOURCE_BUNDLE="$BUILD_DIR/LiteratureRadar_LiteratureRadar.bundle"

if [[ ! -x "$EXECUTABLE" ]]; then
    echo "Missing executable: $EXECUTABLE" >&2
    exit 1
fi

if [[ ! -d "$RESOURCE_BUNDLE" ]]; then
    echo "Missing resource bundle: $RESOURCE_BUNDLE" >&2
    exit 1
fi

/bin/rm -rf "$APP_BUNDLE"
/bin/mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

/bin/cp "$EXECUTABLE" "$MACOS_DIR/$APP_NAME"
/usr/bin/ditto "$RESOURCE_BUNDLE" "$RESOURCES_DIR/LiteratureRadar_LiteratureRadar.bundle"

/bin/cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

/usr/bin/plutil -lint "$CONTENTS_DIR/Info.plist" >/dev/null

SIGN_IDENTITY="${LITRADAR_CODESIGN_IDENTITY:--}"
if ! /usr/bin/codesign --force --deep --sign "$SIGN_IDENTITY" --identifier "$BUNDLE_ID" "$APP_BUNDLE" >/dev/null 2>&1; then
    echo "Warning: codesign failed; the app bundle was created unsigned." >&2
fi

echo "$APP_BUNDLE"
