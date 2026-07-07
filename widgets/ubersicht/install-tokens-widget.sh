#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/tokens.widget"
DEST_ROOT="${HOME}/Library/Application Support/Übersicht/widgets"
DEST="${DEST_ROOT}/tokens.widget"

mkdir -p "${DEST_ROOT}"
rm -rf "${DEST}"
cp -R "${SRC}" "${DEST}"

if /usr/bin/pgrep -x "Übersicht" >/dev/null 2>&1; then
  /usr/bin/osascript -e 'tell application "Übersicht" to refresh' >/dev/null 2>&1 || true
fi

echo "Installed tokens.widget to ${DEST}"
echo "Open Übersicht and choose Refresh All Widgets if it is not visible."
