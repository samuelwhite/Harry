#!/usr/bin/env bash
set -euo pipefail

: "${HARRY_BASE_URL:?Set HARRY_BASE_URL, e.g. http://192.168.1.10:8787}"

AGENT_DIR="${HARRY_AGENT_DIR:-/opt/harry/agent}"
AGENT_PATH="${AGENT_DIR}/harry_agent.sh"
TMP_AGENT="$(mktemp /tmp/harry_agent_install.XXXXXX.sh)"
ALLOW_REPOINT="${HARRY_ALLOW_REPOINT:-0}"

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

ensure_required_runtime() {
  local missing=()

  need_cmd curl || missing+=(curl)
  need_cmd python3 || missing+=(python3)

  if [ "${#missing[@]}" -gt 0 ]; then
    echo "==> Installing required runtime packages..."
    install_packages "${missing[@]}"
  fi

  need_cmd curl || { echo "ERROR: curl is still missing after install attempt." >&2; exit 1; }
  need_cmd python3 || { echo "ERROR: python3 is still missing after install attempt." >&2; exit 1; }
}

install_optional_enrichers() {
  local pkgs=()

  if need_cmd apt-get; then
    pkgs=(dmidecode util-linux lm-sensors)
  elif need_cmd dnf; then
    pkgs=(dmidecode util-linux lm_sensors)
  elif need_cmd yum; then
    pkgs=(dmidecode util-linux lm_sensors)
  elif need_cmd zypper; then
    pkgs=(dmidecode util-linux sensors)
  elif need_cmd apk; then
    pkgs=(util-linux lm-sensors)
  else
    pkgs=()
  fi

  if [ "${#pkgs[@]}" -gt 0 ]; then
    echo "==> Installing optional hardware enrichment packages..."
    install_packages "${pkgs[@]}" || true
  fi
}

current_configured_base_url() {
  local service_file="/etc/systemd/system/harry-agent.service"
  if [ -f "$service_file" ]; then
    awk -F= '/Environment="HARRY_BASE_URL=/{print $2}' "$service_file" \
      | sed 's/"$//' \
      | head -n1
    return 0
  fi
  echo ""
}

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: install-agent.sh must be run as root (or via sudo)." >&2
  exit 1
fi

if ! need_cmd systemctl; then
  echo "ERROR: systemctl not found. Harry agent installer currently requires systemd." >&2
  exit 1
fi

ensure_required_runtime
install_optional_enrichers

EXISTING_BASE_URL="$(current_configured_base_url || true)"
if [ -n "${EXISTING_BASE_URL:-}" ] && [ "${EXISTING_BASE_URL%/}" != "${HARRY_BASE_URL%/}" ]; then
  if [ "$ALLOW_REPOINT" != "1" ]; then
    echo "ERROR: Existing Harry agent is already configured for a different Brain." >&2
    echo "Existing: ${EXISTING_BASE_URL}" >&2
    echo "Requested: ${HARRY_BASE_URL}" >&2
    echo "Refusing to silently repoint this node." >&2
    echo "To override intentionally, rerun with:" >&2
    echo "  HARRY_ALLOW_REPOINT=1" >&2
    exit 1
  fi
  echo "WARNING: Repoint override accepted." >&2
  echo "         Existing: ${EXISTING_BASE_URL}" >&2
  echo "         New:      ${HARRY_BASE_URL}" >&2
fi

mkdir -p "$AGENT_DIR"

echo "==> Downloading Harry agent from ${HARRY_BASE_URL}/dist/harry_agent.sh"
curl -fsSL "${HARRY_BASE_URL}/dist/harry_agent.sh" -o "$TMP_AGENT"

if [ ! -s "$TMP_AGENT" ]; then
  echo "ERROR: downloaded agent was empty." >&2
  rm -f "$TMP_AGENT" >/dev/null 2>&1 || true
  exit 1
fi

if ! bash -n "$TMP_AGENT" >/dev/null 2>&1; then
  echo "ERROR: downloaded agent failed bash syntax validation." >&2
  rm -f "$TMP_AGENT" >/dev/null 2>&1 || true
  exit 1
fi

install -d "$AGENT_DIR"
install -m 0755 "$TMP_AGENT" "$AGENT_PATH"
rm -f "$TMP_AGENT" >/dev/null 2>&1 || true

echo "==> Installing systemd unit files"

cat > /etc/systemd/system/harry-agent.service <<EOF_UNIT
[Unit]
Description=Harry Agent snapshot sender
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
Group=root
Environment="HARRY_SELF_UPDATE=1"
Environment="HARRY_BASE_URL=${HARRY_BASE_URL}"
Environment="HARRY_INGEST_URL=${HARRY_BASE_URL}/ingest"
ExecStart=${AGENT_PATH}
SuccessExitStatus=0
EOF_UNIT

cat > /etc/systemd/system/harry-agent.timer <<'EOF_TIMER'
[Unit]
Description=Run Harry Agent every 5 minutes

[Timer]
OnBootSec=15s
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF_TIMER

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling and starting harry-agent.timer"
systemctl enable --now harry-agent.timer

echo "==> Triggering immediate first agent run"
if systemctl start harry-agent.service; then
  echo "==> First agent run triggered."
else
  echo "WARNING: harry-agent.service failed to start cleanly." >&2
fi

TIMER_ENABLED="$(systemctl is-enabled harry-agent.timer 2>/dev/null || true)"
TIMER_ACTIVE="$(systemctl is-active harry-agent.timer 2>/dev/null || true)"
SERVICE_ACTIVE="$(systemctl is-active harry-agent.service 2>/dev/null || true)"

echo
echo "✅ Harry Agent installed."
echo "Agent:  ${AGENT_PATH}"
echo "Timer enabled: ${TIMER_ENABLED:-unknown}"
echo "Timer active:  ${TIMER_ACTIVE:-unknown}"
if [[ "${SERVICE_ACTIVE}" == "inactive" ]]; then
  echo "Service state: inactive (normal for oneshot service)"
else
  echo "Service state: ${SERVICE_ACTIVE:-unknown}"
fi
echo "Bootstrapping: waiting for first check-in..."
echo "Timer:  systemctl status harry-agent.timer --no-pager"
echo "Run now: systemctl start harry-agent.service"
echo "Logs:   journalctl -u harry-agent.service --since '15 min ago' --no-pager"
