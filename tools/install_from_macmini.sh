#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${DASHBOARD_REMOTE:-origin}"
BRANCH="${DASHBOARD_BRANCH:-main}"
APP="/Applications/Jehyun Dashboard Widgets.app"

cd "$ROOT"

current_branch="$(git branch --show-current)"
if [ "$current_branch" != "$BRANCH" ]; then
  printf %sn "Refusing install from branch ${current_branch}; expected ${BRANCH}."
  exit 1
fi

if ! git diff --quiet -- .; then
  printf %sn "Refusing install with local tracked modifications. Dashboard source is authored on Mac mini."
  git status --short
  exit 1
fi

if ! git diff --cached --quiet -- .; then
  printf %sn "Refusing install with staged local modifications. Dashboard source is authored on Mac mini."
  git status --short
  exit 1
fi

git fetch "$REMOTE" "$BRANCH"
git merge --ff-only "$REMOTE/$BRANCH"
git config core.hooksPath .githooks

./widgets/widgetkit/build-install.sh
killall chronod >/dev/null 2>&1 || true
open "$APP"

if [ "${INSTALL_UBERSICHT_WIDGET:-0}" = "1" ] && [ -x ./widgets/ubersicht/install-tokens-widget.sh ]; then
  ./widgets/ubersicht/install-tokens-widget.sh
fi

printf Installed dashboard widgets from %s/%s at %s.n "$REMOTE" "$BRANCH" "$(git rev-parse --short HEAD)"
