#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/opt/harry"
AGENT_SCRIPT="${ROOT_DIR}/agent/harry_agent.sh"
SERVICE_NAME="harry-agent.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: update-harry.sh must be run as root (or via sudo)." >&2
  exit 1
fi

if [ ! -d "$ROOT_DIR/.git" ]; then
  echo "ERROR: $ROOT_DIR does not look like a Harry git checkout." >&2
  exit 1
fi

cd "$ROOT_DIR"

STASHED="0"
if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
  echo "==> Stashing local changes before update"
  git stash push --include-untracked -m "update-harry auto-stash $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  STASHED="1"
fi

echo "==> Pulling latest Harry changes"
git pull

echo "==> Rebuilding and restarting Harry Brain containers"
docker compose up -d --build

echo "==> Fixing local agent permissions"
chmod +x "$AGENT_SCRIPT"
chmod o+x "$ROOT_DIR" "$ROOT_DIR/agent"

if command -v systemctl >/dev/null 2>&1; then
  echo "==> Reloading systemd"
  systemctl daemon-reload

  if systemctl list-unit-files --type=service 2>/dev/null | awk '{print $1}' | grep -qx "$SERVICE_NAME"; then
    echo "==> Restarting local Harry Agent service"
    systemctl restart "$SERVICE_NAME"

    EXEC_STATUS="$(systemctl show -p ExecMainStatus --value "$SERVICE_NAME" 2>/dev/null || true)"
    if [ "$EXEC_STATUS" = "0" ]; then
      echo "==> harry-agent.service exited 0"
    else
      echo "WARNING: harry-agent.service did not report ExecMainStatus=0." >&2
      systemctl status "$SERVICE_NAME" --no-pager || true
    fi
  else
    echo "==> harry-agent.service is not installed; skipping service restart."
  fi
else
  echo "==> systemctl not available; skipping service restart."
fi

echo "==> Docker container status"
docker compose ps

if [ "$STASHED" = "1" ]; then
  echo "==> Local changes were stashed before the update."
  echo "    Use 'git stash list' if you want to re-apply them."
fi
