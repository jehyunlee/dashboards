#!/usr/bin/env bash
set -euo pipefail

MACMINI_HOST="${DASHBOARD_MACMINI_HOST:-100.114.66.16}"
MACMINI_REPO="${DASHBOARD_MACMINI_REPO:-/Users/jehyunlee/pc_agent/dashboards}"

if [ "$#" -eq 0 ]; then
  set -- git status --short
fi

remote_cmd=""
printf -v remote_cmd %q  "$@"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$MACMINI_HOST" "cd \"$MACMINI_REPO\" && $remote_cmd"
