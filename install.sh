#!/usr/bin/env bash
set -euo pipefail

# Harry Brain installer
# - installer-grade: idempotent, minimal deps, safe defaults

PORT="8787"
LISTEN="0.0.0.0"
INSTALL_DIR="${HOME}/harry"
PROJECT="harry"
SKIP_BUILD="0"
INSTALL_LOCAL_AGENT="1"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Options:
  --dir PATH        Install directory (default: ~/harry)
  --port PORT       Host port to expose (default: 8787)
  --listen ADDR     Address to bind on host (default: 0.0.0.0)
                   (use 127.0.0.1 for local-only)
  --project NAME    Docker compose project name (default: harry)
  --skip-build      Do not build image
  --no-local-agent  Do not install the local node agent
  -h, --help        Show help

Examples:
  ./install.sh
  ./install.sh --listen 127.0.0.1
  ./install.sh --dir ~/harry-test --project harrytest --port 8788
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --listen) LISTEN="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD="1"; shift 1 ;;
    --no-local-agent) INSTALL_LOCAL_AGENT="0"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_packages() {
  if [ "$#" -eq 0 ]; then
    return 0
  fi

  echo "==> Installing packages: $*"

  if need_cmd apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y "$@"
    return 0
  fi

  if need_cmd dnf; then
    dnf install -y "$@"
    return 0
  fi

  if need_cmd yum; then
    yum install -y "$@"
    return 0
  fi

  if need_cmd zypper; then
    zypper --non-interactive install "$@"
    return 0
  fi

  if need_cmd apk; then
    apk add --no-cache "$@"
    return 0
  fi

  echo "ERROR: No supported package manager found to install: $*" >&2
  exit 1
}

ensure_curl() {
  if need_cmd curl; then
    return 0
  fi

  echo "==> curl not found. Attempting to install it..."
  install_packages curl

  if ! need_cmd curl; then
    echo "ERROR: curl is required but could not be installed." >&2
    exit 1
  fi
}

require_cmd_or_fail() {
  local cmd="$1"
  local help_msg="${2:-}"

  if ! need_cmd "$cmd"; then
    echo "ERROR: Missing dependency: $cmd" >&2
    if [ -n "$help_msg" ]; then
      echo "$help_msg" >&2
    fi
    exit 1
  fi
}

ensure_curl

require_cmd_or_fail docker "Install Docker first, then rerun ./install.sh"

# Docker compose detection
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found." >&2
  echo "Install the Docker Compose plugin or docker-compose, then rerun ./install.sh" >&2
  exit 1
fi

# Port check
if command -v ss >/dev/null 2>&1; then
  if ss -ltn | awk '{print $4}' | grep -qE "[:.]${PORT}\$"; then
    echo "WARNING: Port ${PORT} appears to be in use already." >&2
    echo "         If install fails, try --port 8788." >&2
  fi
fi

echo "==> Installing Harry Brain into: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$INSTALL_DIR" in
  ""|"/"|".")
    echo "Refusing unsafe install directory: '$INSTALL_DIR'" >&2
    exit 1
    ;;
esac

# Clean install directory
find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

# Copy runtime files
cp -a "$SCRIPT_DIR/Dockerfile" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/docker-compose.yml" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/app" "$INSTALL_DIR/"

if [[ -d "$SCRIPT_DIR/scripts" ]]; then
  cp -a "$SCRIPT_DIR/scripts" "$INSTALL_DIR/"
fi

# Determine hostname for brain node
BRAIN_NODE_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo brain)"
echo "==> Brain node name: ${BRAIN_NODE_NAME}"

# Write env file
cat > "$INSTALL_DIR/.env" <<ENV
HARRY_DB_PATH=/data/harry.db
HARRY_DATA_DIR=/data
HARRY_BRAIN_NODE=${BRAIN_NODE_NAME}
ENV

# Write compose override
cat > "$INSTALL_DIR/docker-compose.override.yml" <<OVR
services:
  harry-brain:
    ports:
      - "${LISTEN}:${PORT}:8787"
OVR

echo "==> Starting containers..."

pushd "$INSTALL_DIR" >/dev/null

if [[ "$SKIP_BUILD" == "1" ]]; then
  "${DOCKER_COMPOSE[@]}" -p "$PROJECT" up -d
else
  "${DOCKER_COMPOSE[@]}" -p "$PROJECT" up -d --build
fi

popd >/dev/null

LOCAL_AGENT_INSTALL_OK="0"
LOCAL_AGENT_CHECKIN_OK="0"

# -------------------------------------------------------------------
# Install local agent if enabled
# -------------------------------------------------------------------
if [[ "${INSTALL_LOCAL_AGENT:-1}" == "1" ]]; then
  echo
  echo "==> Waiting for Harry Brain to become ready..."

  READY="0"

  for i in {1..30}; do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      READY="1"
      break
    fi
    sleep 1
  done

  if [[ "$READY" != "1" ]]; then
    echo "WARNING: Harry Brain did not become ready in time." >&2
    echo "         Skipping local agent install." >&2
  else
    echo "==> Harry Brain is ready."
    echo "==> Installing local Harry agent on this machine..."

    if [[ ! -f "$INSTALL_DIR/scripts/install-agent.sh" ]]; then
      echo "WARNING: Local agent installer not found." >&2
      echo "         Skipping local agent install." >&2
    else
      set +e
      if command -v sudo >/dev/null 2>&1; then
        sudo env HARRY_BASE_URL="http://127.0.0.1:${PORT}" \
          bash "$INSTALL_DIR/scripts/install-agent.sh"
      else
        env HARRY_BASE_URL="http://127.0.0.1:${PORT}" \
          bash "$INSTALL_DIR/scripts/install-agent.sh"
      fi
      INSTALL_EXIT=$?
      set -e

      if [[ "$INSTALL_EXIT" -eq 0 ]]; then
        LOCAL_AGENT_INSTALL_OK="1"
        echo "==> Local agent install completed."
        echo "==> Waiting for first local check-in..."

        for i in {1..30}; do
          if curl -fsS "http://127.0.0.1:${PORT}/nodes" 2>/dev/null | grep -q "\"node\":\"${BRAIN_NODE_NAME}\""; then
            LOCAL_AGENT_CHECKIN_OK="1"
            break
          fi
          sleep 1
        done

        if [[ "$LOCAL_AGENT_CHECKIN_OK" == "1" ]]; then
          echo "==> Local node check-in confirmed."
        else
          echo "==> Local agent is bootstrapping. First check-in has not appeared yet."
        fi
      else
        echo "WARNING: Local agent installer exited with code ${INSTALL_EXIT}." >&2
      fi
    fi
  fi
fi

# -------------------------------------------------------------------
# Final success output
# -------------------------------------------------------------------

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

if [ "$LISTEN" = "127.0.0.1" ]; then
  HOST_IP="127.0.0.1"
else
  HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  HOST_IP="${HOST_IP:-$(hostname 2>/dev/null || echo localhost)}"
fi

echo
echo "OK Harry Brain is up (or starting)."
echo
echo "UI:     http://${HOST_IP}:${PORT}/"
echo "Health: http://${HOST_IP}:${PORT}/health"
echo "Dist:   http://${HOST_IP}:${PORT}/dist/harry_agent.sh"

if [[ "${INSTALL_LOCAL_AGENT:-1}" == "1" ]]; then
  echo
  if [[ "$LOCAL_AGENT_INSTALL_OK" == "1" && "$LOCAL_AGENT_CHECKIN_OK" == "1" ]]; then
    echo "Local agent: installed and checked in."
  elif [[ "$LOCAL_AGENT_INSTALL_OK" == "1" ]]; then
    echo "Local agent: installed and bootstrapping."
  else
    echo "Local agent: not confirmed."
  fi
fi

echo
echo "Tip: If you're going internet-facing, put this behind a reverse proxy + HTTPS."
