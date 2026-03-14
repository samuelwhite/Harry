#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/agent/windows"
DIST="$ROOT/app/dist/windows"
INSTALLERS="$ROOT/installers"

VERSION="${1:-$(date +%Y.%m.%d)}"
ZIP_NAME="harry-agent-windows-${VERSION}.zip"
ZIP_PATH="$INSTALLERS/$ZIP_NAME"

echo "==> Preparing Windows dist folder"
rm -rf "$DIST"
mkdir -p "$DIST"
mkdir -p "$INSTALLERS"

echo "==> Copying Windows support files"
cp "$SRC/install_agent.ps1" "$DIST/install_agent.ps1"
cp "$SRC/uninstall_agent.ps1" "$DIST/uninstall_agent.ps1"
cp "$SRC/agent_config.sample.json" "$DIST/agent_config.sample.json"
cp "$SRC/README.txt" "$DIST/README.txt"
cp "$SRC/START-HERE.txt" "$DIST/START-HERE.txt"
cp "$SRC/HarryAgentService.xml" "$DIST/HarryAgentService.xml"

echo "==> Checking for WinSW service wrapper"
if [[ -f "$SRC/HarryAgentService.exe" ]]; then
  cp "$SRC/HarryAgentService.exe" "$DIST/HarryAgentService.exe"
  echo "Copied HarryAgentService.exe"
else
  echo "WARNING: $SRC/HarryAgentService.exe not found"
  echo "Package will be incomplete until HarryAgentService.exe is added"
fi

echo "==> Checking for prebuilt Windows agent exe"
if [[ -f "$SRC/harry_agent.exe" ]]; then
  cp "$SRC/harry_agent.exe" "$DIST/harry_agent.exe"
  echo "Copied prebuilt harry_agent.exe"
else
  echo "WARNING: $SRC/harry_agent.exe not found"
  echo "Package will be incomplete until a Windows-built harry_agent.exe is added"
fi

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
