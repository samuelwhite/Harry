#!/usr/bin/env bash
set -euo pipefail

# Harry Brain installer
# - installer-grade: idempotent, minimal deps, safe defaults

PORT="8787"
LISTEN="0.0.0.0"              # 0.0.0.0 = LAN-friendly, 127.0.0.1 = local-only
INSTALL_DIR="${HOME}/harry"
PROJECT="harry"
SKIP_BUILD="0"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Options:
  --dir PATH        Install directory (default: ~/harry)
  --port PORT       Host port to expose (default: 8787)
  --listen ADDR     Address to bind on host (default: 0.0.0.0)
                   (use 127.0.0.1 for local-only)
  --project NAME    Docker compose project name (default: harry)
  --skip-build      Do not build image (assumes images already present)
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

# Docker compose: plugin ("docker compose") preferred
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "Docker Compose not found. Install the Docker Compose plugin or docker-compose." >&2
  exit 1
fi

# Port sanity (best-effort)
if command -v ss >/dev/null 2>&1; then
  if ss -ltn | awk '{print $4}' | grep -qE "[:.]${PORT}\$"; then
    echo "WARNING: Port ${PORT} appears to be in use already." >&2
    echo "         If this install fails, try --port 8788 (or stop the other service)." >&2
  fi
fi

echo "==> Installing Harry Brain into: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Refuse obviously dangerous install targets
case "$INSTALL_DIR" in
  ""|"/"|".")
    echo "Refusing unsafe install directory: '$INSTALL_DIR'" >&2
    exit 1
    ;;
esac

# Clean install dir safely, including hidden files
find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

# Copy only runtime files needed for Harry Brain
cp -a "$SCRIPT_DIR/Dockerfile" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/docker-compose.yml" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/app" "$INSTALL_DIR/"

if [[ -d "$SCRIPT_DIR/scripts" ]]; then
  cp -a "$SCRIPT_DIR/scripts" "$INSTALL_DIR/"
fi

# Write env file (compose can read it; app also reads env vars)
cat > "$INSTALL_DIR/.env" <<ENV
HARRY_DB_PATH=/data/harry.db
HARRY_DATA_DIR=/data
ENV

# Write an install-specific compose override with port binding
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

# Best-guess host IP for instructions
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
echo "Agent install (copy/paste on a node):"
cat <<AGENT
export HARRY_BASE_URL="http://${HOST_IP}:${PORT}"
curl -fsSL "\$HARRY_BASE_URL/scripts/install-agent.sh" | sudo -E bash
AGENT
echo
echo "Tip: If you're going internet-facing, put this behind a reverse proxy + HTTPS, then set HARRY_BASE_URL to that."
