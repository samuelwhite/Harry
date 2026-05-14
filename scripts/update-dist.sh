#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/agent/harry_agent.sh"
DST="$ROOT_DIR/app/dist/harry_agent.sh"
INSTALL_SRC="$ROOT_DIR/scripts/install-agent.sh"
INSTALL_DST="$ROOT_DIR/downloads/HarryAgentInstall.sh"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: source agent not found: $SRC" >&2
  exit 1
fi

# Basic sanity: must start with bash shebang
head -n 1 "$SRC" | grep -qE '^#!/usr/bin/env bash|^#!/bin/bash' || {
  echo "ERROR: source agent does not appear to be a bash script (missing shebang)." >&2
  exit 1
}

install -m 0755 "$SRC" "$DST"
install -m 0755 "$INSTALL_SRC" "$INSTALL_DST"

# Show hashes so you can see it worked
echo "Updated dist agent:"
echo "Updated Linux installer:"
sha256sum "$INSTALL_SRC" "$INSTALL_DST" | sed "s|$ROOT_DIR/||g"
sha256sum "$SRC" "$DST" | sed "s|$ROOT_DIR/||g"
