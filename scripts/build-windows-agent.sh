#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/app/dist/windows"
INSTALLERS="$ROOT/installers"
SYNCER="$ROOT/scripts/sync_windows_artifacts.py"
PYTHON_BIN="${PYTHON:-python}"

VERSION="${1:-$(date +%Y.%m.%d)}"
ZIP_NAME="harry-agent-windows-${VERSION}.zip"
ZIP_PATH="$INSTALLERS/$ZIP_NAME"

echo "==> Preparing Windows dist folder"
"$PYTHON_BIN" "$SYNCER" --root "$ROOT"

mkdir -p "$INSTALLERS"

echo "==> Building installer zip"
if ! command -v zip >/dev/null 2>&1; then
  echo "ERROR: zip command not found"
  exit 1
fi

rm -f "$ZIP_PATH"
(
  cd "$ROOT/app/dist"
  zip -r "$ZIP_PATH" windows >/dev/null
)

echo "==> Windows dist ready at: $DIST"
find "$DIST" -maxdepth 1 -type f | sort
echo
echo "==> Installer zip ready at: $ZIP_PATH"
ls -lh "$ZIP_PATH"
