#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${ROOT}/Sources"
BUILD="${ROOT}/.build"
APP_NAME="Jehyun Dashboard Widgets"
APP_BUNDLE_ID="dev.jehyunlee.dashboards.TokenWidgets"
APP_EXEC="JehyunDashboardWidgets"
MIN_TARGET="arm64-apple-macos14.0"
INSTALL_ROOT="${INSTALL_ROOT:-/Applications}"
BUILD_NUMBER="${DASHBOARD_WIDGET_BUILD:-$(/bin/date -u +%Y%m%d%H%M%S)}"
APP="${BUILD}/${APP_NAME}.app"
PLUGINS="${APP}/Contents/PlugIns"

rm -rf "${BUILD}"
mkdir -p "${APP}/Contents/MacOS" "${PLUGINS}" "${INSTALL_ROOT}"
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

build_extension() {
  local ext_name="$1"
  local display_name="$2"
  local define_flag="$3"
  local ext="${PLUGINS}/${ext_name}.appex"
  local bundle_id="${APP_BUNDLE_ID}.${ext_name}"

  mkdir -p "${ext}/Contents/MacOS"

  if [ -n "${define_flag}" ]; then
    /usr/bin/swiftc \
      -target "${MIN_TARGET}" \
      -parse-as-library \
      -application-extension \
      -framework SwiftUI \
      -framework WidgetKit \
      -Xlinker -e \
      -Xlinker _NSExtensionMain \
      -D "${define_flag}" \
      "${SRC}/TokenStatusWidget.swift" \
      -o "${ext}/Contents/MacOS/${ext_name}"
  else
    /usr/bin/swiftc \
      -target "${MIN_TARGET}" \
      -parse-as-library \
      -application-extension \
      -framework SwiftUI \
      -framework WidgetKit \
      -Xlinker -e \
      -Xlinker _NSExtensionMain \
      "${SRC}/TokenStatusWidget.swift" \
      -o "${ext}/Contents/MacOS/${ext_name}"
  fi

  cat > "${ext}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>ko</string>
  <key>CFBundleExecutable</key><string>${ext_name}</string>
  <key>CFBundleIdentifier</key><string>${bundle_id}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${ext_name}</string>
  <key>CFBundleDisplayName</key><string>${display_name}</string>
  <key>CFBundlePackageType</key><string>XPC!</string>
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundleVersion</key><string>${BUILD_NUMBER}</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSExtension</key>
  <dict>
    <key>NSExtensionPointIdentifier</key><string>com.apple.widgetkit-extension</string>
  </dict>
</dict>
</plist>
PLIST

  /usr/bin/codesign --force --sign - --timestamp=none --entitlements "${BUILD}/Widget.entitlements" "${ext}"
}

build_extension "TokenStatusWidgetExtension" "Token Matrix" ""
build_extension "OpenAITokenWidgetExtension" "OpenAI Token Status" "PROVIDER_OPENAI"
build_extension "AnthropicTokenWidgetExtension" "Anthropic Token Status" "PROVIDER_ANTHROPIC"
build_extension "GoogleTokenWidgetExtension" "Google Token Status" "PROVIDER_GOOGLE"

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
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundleVersion</key><string>${BUILD_NUMBER}</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

/usr/bin/codesign --force --sign - --timestamp=none --entitlements "${BUILD}/App.entitlements" "${APP}"

DEST="${INSTALL_ROOT}/${APP_NAME}.app"
rm -rf "${DEST}"
cp -R "${APP}" "${DEST}"
/usr/bin/xattr -dr com.apple.quarantine "${DEST}" 2>/dev/null || true

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "${LSREGISTER}" ]; then
  "${LSREGISTER}" -f "${DEST}" >/dev/null 2>&1 || true
fi
for ext_name in TokenStatusWidgetExtension OpenAITokenWidgetExtension AnthropicTokenWidgetExtension GoogleTokenWidgetExtension; do
  /usr/bin/pluginkit -a "${DEST}/Contents/PlugIns/${ext_name}.appex" >/dev/null 2>&1 || true
done
/usr/bin/open "${DEST}"

printf 'Installed %s\n' "${DEST}"
printf 'Widgets: Token Matrix, OpenAI Token Status, Anthropic Token Status, Google Token Status.\n'
printf 'Add them from Desktop → Edit Widgets… → Jehyun Dashboards.\n'
printf 'If the widget gallery is stale, wait briefly or log out/in.\n'
