#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${ROOT}/Sources"
BUILD="${ROOT}/.build"
APP_NAME="Jehyun Dashboard Widgets"
APP_BUNDLE_ID="dev.jehyunlee.dashboards.TokenWidgets"
APP_EXEC="JehyunDashboardWidgets"
EXT_NAME="TokenStatusWidgetExtension"
EXT_BUNDLE_ID="${APP_BUNDLE_ID}.${EXT_NAME}"
MIN_TARGET="arm64-apple-macos14.0"
INSTALL_ROOT="${INSTALL_ROOT:-/Applications}"
APP="${BUILD}/${APP_NAME}.app"
EXT="${APP}/Contents/PlugIns/${EXT_NAME}.appex"

rm -rf "${BUILD}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/PlugIns" "${EXT}/Contents/MacOS" "${INSTALL_ROOT}"
cat > "${BUILD}/App.entitlements" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key><true/>
</dict>
</plist>
PLIST

cat > "${BUILD}/Widget.entitlements" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key><true/>
  <key>com.apple.security.network.client</key><true/>
</dict>
</plist>
PLIST


/usr/bin/swiftc \
  -target "${MIN_TARGET}" \
  -parse-as-library \
  -framework SwiftUI \
  "${SRC}/HostApp.swift" \
  -o "${APP}/Contents/MacOS/${APP_EXEC}"

/usr/bin/swiftc \
  -target "${MIN_TARGET}" \
  -parse-as-library \
  -application-extension \
  -framework SwiftUI \
  -framework WidgetKit \
  -Xlinker -e \
  -Xlinker _NSExtensionMain \
  "${SRC}/TokenStatusWidget.swift" \
  -o "${EXT}/Contents/MacOS/${EXT_NAME}"

cat > "${APP}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>ko</string>
  <key>CFBundleExecutable</key><string>${APP_EXEC}</string>
  <key>CFBundleIdentifier</key><string>${APP_BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>Jehyun Dashboards</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "${EXT}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>ko</string>
  <key>CFBundleExecutable</key><string>${EXT_NAME}</string>
  <key>CFBundleIdentifier</key><string>${EXT_BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${EXT_NAME}</string>
  <key>CFBundleDisplayName</key><string>Token Status</string>
  <key>CFBundlePackageType</key><string>XPC!</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSExtension</key>
  <dict>
    <key>NSExtensionPointIdentifier</key><string>com.apple.widgetkit-extension</string>
  </dict>
</dict>
</plist>
PLIST

/usr/bin/codesign --force --sign - --timestamp=none --entitlements "${BUILD}/Widget.entitlements" "${EXT}"
/usr/bin/codesign --force --sign - --timestamp=none --entitlements "${BUILD}/App.entitlements" "${APP}"

DEST="${INSTALL_ROOT}/${APP_NAME}.app"
rm -rf "${DEST}"
cp -R "${APP}" "${DEST}"
/usr/bin/xattr -dr com.apple.quarantine "${DEST}" 2>/dev/null || true

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "${LSREGISTER}" ]; then
  "${LSREGISTER}" -f "${DEST}" >/dev/null 2>&1 || true
fi
/usr/bin/pluginkit -a "${DEST}/Contents/PlugIns/${EXT_NAME}.appex" >/dev/null 2>&1 || true
/usr/bin/open "${DEST}"

echo "Installed ${DEST}"
echo "Add it from Desktop → Edit Widgets… → Jehyun Dashboards → Token Status."
echo "If it does not appear immediately, log out/in or run: pluginkit -m -i ${EXT_BUNDLE_ID}"
