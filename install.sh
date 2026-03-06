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
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1" >&2
    exit 1
  }
}

need_cmd docker
need_cmd curl

# Docker compose detection
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "Docker Compose not found." >&2
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

echo "==> Starting containers…"

pushd "$INSTALL_DIR" >/dev/null

if [[ "$SKIP_BUILD" == "1" ]]; then
  "${DOCKER_COMPOSE[@]}" -p "$PROJECT" up -d
else
  "${DOCKER_COMPOSE[@]}" -p "$PROJECT" up -d --build
fi

popd >/dev/null

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

    echo "==> Installing local Harry agent on this machine..."

    if [[ ! -f "$INSTALL_DIR/scripts/install-agent.sh" ]]; then
      echo "WARNING: Local agent installer not found." >&2
      echo "         Skipping local agent install." >&2
    else

      if command -v sudo >/dev/null 2>&1; then
        sudo env HARRY_BASE_URL="http://127.0.0.1:${PORT}" \
          bash "$INSTALL_DIR/scripts/install-agent.sh"
      else
        env HARRY_BASE_URL="http://127.0.0.1:${PORT}" \
          bash "$INSTALL_DIR/scripts/install-agent.sh"
      fi

    fi

  fi

fi

# -------------------------------------------------------------------
# Final success output
# -------------------------------------------------------------------

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

if [[ -z "${HOST_IP:-}" ]]; then
  HOST_IP="localhost"
fi

echo
echo "OK Harry Brain is up (or starting)."
echo
echo "UI:     http://${HOST_IP}:${PORT}/"
echo "Health: http://${HOST_IP}:${PORT}/health"
echo "Dist:   http://${HOST_IP}:${PORT}/dist/harry_agent.sh"
echo
echo "Tip: If you're going internet-facing, put this behind a reverse proxy + HTTPS."
