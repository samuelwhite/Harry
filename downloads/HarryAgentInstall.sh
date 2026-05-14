#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="${HARRY_AGENT_DIR:-/opt/harry/agent}"
AGENT_PATH="${AGENT_DIR}/harry_agent.sh"
TMP_AGENT="$(mktemp /tmp/harry_agent_install.XXXXXX.sh)"
ALLOW_REPOINT="${HARRY_ALLOW_REPOINT:-0}"
INSTALL_ROOT="${HARRY_INSTALL_DIR:-}"
HARRY_BASE_URL="${HARRY_BASE_URL:-}"
HARRY_PUBLIC_BASE_URL="${HARRY_PUBLIC_BASE_URL:-}"
HARRY_INGEST_URL="${HARRY_INGEST_URL:-}"
HARRY_URL="${HARRY_URL:-}"
HARRY_PUBLIC_PORT="${HARRY_PUBLIC_PORT:-8789}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGED_AGENT_SCRIPT="$SCRIPT_DIR/harry_agent.sh"
DEV_AGENT_SCRIPT="$SCRIPT_DIR/../agent/harry_agent.sh"
DISCOVERY_HELPER="$SCRIPT_DIR/brain_discovery.py"
PYTHON="${PYTHON:-python3}"

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
  if ! need_cmd python3 && ! need_cmd python; then
    missing+=(python3)
  fi

  if [ "${#missing[@]}" -gt 0 ]; then
    echo "==> Installing required runtime packages..."
    install_packages "${missing[@]}"
  fi

  need_cmd curl || { echo "ERROR: curl is still missing after install attempt." >&2; exit 1; }
  if ! need_cmd python3 && ! need_cmd python; then
    echo "ERROR: python3/python is still missing after install attempt." >&2
    exit 1
  fi
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

detect_platform() {
  case "${HARRY_PLATFORM:-}" in
    synology-dsm|linux-systemd|linux-generic)
      echo "$HARRY_PLATFORM"
      return 0
      ;;
  esac

  if [ -f /etc.defaults/VERSION ] && [ -f /etc/synoinfo.conf ]; then
    echo "synology-dsm"
    return 0
  fi

  if need_cmd systemctl && [ -d /run/systemd/system ]; then
    echo "linux-systemd"
    return 0
  fi

  echo "linux-generic"
}

resolve_synology_install_root() {
  if [ -n "${INSTALL_ROOT:-}" ]; then
    case "$INSTALL_ROOT" in
      ""|"/"|".")
        echo ""
        return 1
        ;;
    esac
    echo "$INSTALL_ROOT"
    return 0
  fi

  local install_user="${HARRY_INSTALL_USER:-${SUDO_USER:-}}"
  local home_candidate=""
  local volume_candidate=""
  local volume

  if [ -n "$install_user" ] && [ -d "/var/services/homes" ]; then
    home_candidate="/var/services/homes/${install_user}/harry"
    echo "$home_candidate"
    return 0
  fi

  for volume in /volume*; do
    if [ -d "$volume" ]; then
      volume_candidate="${volume%/}/@harry"
      echo "$volume_candidate"
      return 0
    fi
  done

  if [ -n "$install_user" ]; then
    home_candidate="/var/services/homes/${install_user}/harry"
    echo "$home_candidate"
    return 0
  fi

  echo ""
  return 1
}

read_configured_value() {
  local file="$1"
  shift
  local key line value

  if [ ! -f "$file" ]; then
    return 1
  fi

  for key in "$@"; do
    line="$(
      grep -m1 -E "${key}=" "$file" 2>/dev/null || true
    )"
    if [ -n "$line" ]; then
      value="${line#*${key}=}"
      value="${value#\"}"
      value="${value%\"}"
      printf '%s\n' "$value"
      return 0
    fi
  done

  return 1
}

current_configured_base_url() {
  local platform="${1:-}"
  local install_root="${2:-}"
  local service_file="/etc/systemd/system/harry-agent.service"
  local env_file="${install_root%/}/harry-agent.env"
  local value=""

  if [ "$platform" = "linux-systemd" ] && [ -f "$service_file" ]; then
    value="$(read_configured_value "$service_file" HARRY_PUBLIC_BASE_URL HARRY_BASE_URL || true)"
    if [ -n "$value" ]; then
      echo "$value"
      return 0
    fi
  fi

  if [ "$platform" = "synology-dsm" ] && [ -f "$env_file" ]; then
    value="$(read_configured_value "$env_file" HARRY_PUBLIC_BASE_URL HARRY_BASE_URL || true)"
    if [ -n "$value" ]; then
      echo "$value"
      return 0
    fi
  fi

  echo ""
}

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: install-agent.sh must be run as root (or via sudo)." >&2
  exit 1
fi

PLATFORM="$(detect_platform)"
echo "Detected platform: ${PLATFORM}"

if [ "$PLATFORM" = "synology-dsm" ]; then
  if ! need_cmd python3 && ! need_cmd python; then
    echo "ERROR: python3 (or python) is required for the Harry Agent runtime." >&2
    exit 1
  fi
  if ! need_cmd curl; then
    echo "ERROR: curl is required for the Harry Agent runtime." >&2
    exit 1
  fi
  INSTALL_ROOT="$(resolve_synology_install_root)"
  if [ -z "$INSTALL_ROOT" ]; then
    echo "ERROR: Could not determine a persistent install directory for Synology DSM." >&2
    echo "Set HARRY_INSTALL_DIR to a writable persistent path and rerun." >&2
    exit 1
  fi
  AGENT_DIR="${INSTALL_ROOT%/}/agent"
  AGENT_PATH="${AGENT_DIR}/harry_agent.sh"
  echo "Install mode: DSM Task Scheduler wrapper"
  echo "Install root: ${INSTALL_ROOT}"
else
  if ! need_cmd systemctl; then
    echo "ERROR: systemctl not found. Harry agent installer currently requires systemd outside Synology DSM." >&2
    exit 1
  fi
  echo "Install mode: systemd timer"
fi

if ! need_cmd bash; then
  echo "ERROR: bash not found. Harry Agent requires bash to run." >&2
  exit 1
fi

ensure_required_runtime
install_optional_enrichers

brain_public_port() {
  local port="${HARRY_PUBLIC_PORT:-8789}"
  case "$port" in
    ''|*[!0-9]*)
      echo 8789
      return 0
      ;;
  esac

  if [ "$port" -ge 1 ] && [ "$port" -le 65535 ]; then
    echo "$port"
  else
    echo 8789
  fi
}

trim_brain_url_input() {
  local raw="${1:-}"

  printf '%s' "$raw" \
    | tr -d '\r' \
    | sed -e "s/^[[:space:]]*['\"]*//" -e "s/['\"]*[[:space:]]*$//"
}

debug_brain_url_validation_failure() {
  local sanitized="${1:-}"
  local rule="${2:-unknown}"

  echo "DEBUG: sanitized URL: ${sanitized:-<empty>}" >&2
  echo "DEBUG: validation rule failed: ${rule}" >&2
}

normalize_brain_url() {
  local raw="${1:-}"
  local sanitized=""
  local normalized=""
  local rest=""
  local host=""
  local port=""
  local rule=""

  sanitized="$(trim_brain_url_input "$raw")"
  if [ -z "$sanitized" ]; then
    rule="empty after trimming"
    debug_brain_url_validation_failure "$sanitized" "$rule"
    return 1
  fi

  case "$sanitized" in
    http://*|https://*)
      ;;
    *)
      sanitized="http://${sanitized}"
      ;;
  esac

  rest="${sanitized#*://}"
  if [ -z "$rest" ]; then
    rule="missing host"
    debug_brain_url_validation_failure "$sanitized" "$rule"
    return 1
  fi

  case "$rest" in
    */*)
      if [ "${rest%/}" = "$rest" ]; then
        rule="path segments are not allowed"
        debug_brain_url_validation_failure "$sanitized" "$rule"
        return 1
      fi
      rest="${rest%/}"
      ;;
  esac

  case "$rest" in
    *:*)
      host="${rest%:*}"
      port="${rest##*:}"
      ;;
    *)
      host="$rest"
      port=""
      ;;
  esac

  host="$(trim_brain_url_input "$host")"
  port="$(trim_brain_url_input "$port")"

  if [ -z "$host" ]; then
    rule="host is empty"
    debug_brain_url_validation_failure "$sanitized" "$rule"
    return 1
  fi

  case "$host" in
    *[!A-Za-z0-9.-]*)
      rule="host contains invalid characters"
      debug_brain_url_validation_failure "$sanitized" "$rule"
      return 1
      ;;
    -*|*-|.*|*.)
      rule="host has invalid boundary characters"
      debug_brain_url_validation_failure "$sanitized" "$rule"
      return 1
      ;;
  esac

  if [ -n "$port" ]; then
    case "$port" in
      *[!0-9]*)
        rule="port contains non-digits"
        debug_brain_url_validation_failure "$sanitized" "$rule"
        return 1
        ;;
    esac

    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
      rule="port out of range"
      debug_brain_url_validation_failure "$sanitized" "$rule"
      return 1
    fi
  fi

  normalized="${sanitized%/}"
  printf '%s\n' "$normalized"
}

probe_brain_url() {
  local raw="${1:-}"
  local timeout="${2:-1.2}"
  "$PYTHON" "$DISCOVERY_HELPER" probe "$raw" --timeout "$timeout"
}

discover_brain_urls() {
  "$PYTHON" "$DISCOVERY_HELPER" discover --port "$(brain_public_port)" --timeout 1.2 --workers 32
}

prompt_manual_brain_url() {
  local input=""
  local default_hint="http://<brain-ip>:$(brain_public_port)"

  if [ ! -t 0 ]; then
    echo "ERROR: Unable to auto-discover Harry Brain and no interactive terminal is available." >&2
    echo "Set HARRY_BASE_URL or HARRY_INGEST_URL explicitly, or rerun interactively and enter the Brain address." >&2
    return 1
  fi

  echo "==> Harry Brain could not be auto-discovered."
  echo "    Enter the Brain address that other machines can reach."
  echo "    Examples:"
  echo "      192.168.1.100"
  echo "      192.168.1.100:8789"
  echo "      http://192.168.1.100:8789"
  echo
  read -r -p "Harry Brain address [${default_hint}]: " input || true
  input="${input:-}"
  if [ -z "$input" ]; then
    echo "ERROR: No Brain address provided." >&2
    return 1
  fi

  if ! normalized="$(normalize_brain_url "$input" 2>/dev/null)"; then
    echo "ERROR: Invalid Harry Brain address." >&2
    return 1
  fi

  if ! probe_brain_url "$normalized" >/dev/null 2>&1; then
    echo "ERROR: Harry Brain is not reachable at ${normalized}." >&2
    echo "Set HARRY_BASE_URL or HARRY_INGEST_URL explicitly if discovery cannot find it." >&2
    return 1
  fi

  HARRY_BASE_URL="$normalized"
  echo "==> Using manually entered Harry Brain at ${HARRY_BASE_URL}"
  return 0
}

resolve_brain_url() {
  local discovered=()
  local line
  local normalized

  if [ -n "${HARRY_PUBLIC_BASE_URL:-}" ]; then
    if ! normalized="$(normalize_brain_url "$HARRY_PUBLIC_BASE_URL" 2>/dev/null)"; then
      echo "ERROR: HARRY_PUBLIC_BASE_URL is invalid." >&2
      return 1
    fi
    HARRY_PUBLIC_BASE_URL="$normalized"
    HARRY_BASE_URL="$normalized"
    HARRY_INGEST_URL="${HARRY_INGEST_URL:-$HARRY_BASE_URL/ingest}"
    return 0
  fi

  if [ -n "${HARRY_BASE_URL:-}" ]; then
    if ! normalized="$(normalize_brain_url "$HARRY_BASE_URL" 2>/dev/null)"; then
      echo "ERROR: HARRY_BASE_URL is invalid." >&2
      return 1
    fi
    HARRY_BASE_URL="$normalized"
    HARRY_INGEST_URL="${HARRY_INGEST_URL:-$HARRY_BASE_URL/ingest}"
    return 0
  fi

  if [ -n "${HARRY_INGEST_URL:-}" ]; then
    if [[ "$HARRY_INGEST_URL" == */ingest ]]; then
      HARRY_BASE_URL="${HARRY_INGEST_URL%/ingest}"
    else
      HARRY_BASE_URL="${HARRY_INGEST_URL%/*}"
    fi
    if ! normalized="$(normalize_brain_url "$HARRY_BASE_URL" 2>/dev/null)"; then
      echo "ERROR: HARRY_INGEST_URL is invalid." >&2
      return 1
    fi
    HARRY_BASE_URL="$normalized"
    HARRY_INGEST_URL="${HARRY_INGEST_URL:-$HARRY_BASE_URL/ingest}"
    return 0
  fi

  if [ -n "${HARRY_URL:-}" ]; then
    if [[ "$HARRY_URL" == */ingest ]]; then
      HARRY_BASE_URL="${HARRY_URL%/ingest}"
    else
      HARRY_BASE_URL="${HARRY_URL%/*}"
    fi
    if ! normalized="$(normalize_brain_url "$HARRY_BASE_URL" 2>/dev/null)"; then
      echo "ERROR: HARRY_URL is invalid." >&2
      return 1
    fi
    HARRY_BASE_URL="$normalized"
    HARRY_INGEST_URL="${HARRY_INGEST_URL:-$HARRY_BASE_URL/ingest}"
    return 0
  fi

  while IFS= read -r line; do
    [ -n "$line" ] && discovered+=("$line")
  done < <(discover_brain_urls || true)

  if [ "${#discovered[@]}" -eq 1 ]; then
    HARRY_BASE_URL="${discovered[0]}"
    HARRY_INGEST_URL="${HARRY_BASE_URL%/}/ingest"
    echo "==> Auto-discovered Harry Brain at ${HARRY_BASE_URL}"
    return 0
  fi

  if [ "${#discovered[@]}" -gt 1 ]; then
    if [ ! -t 0 ]; then
      echo "ERROR: Multiple Harry Brain instances were discovered, but the installer is non-interactive." >&2
      printf 'Discovered:\n' >&2
      printf '  - %s\n' "${discovered[@]}" >&2
      echo "Set HARRY_BASE_URL explicitly or rerun interactively to choose one." >&2
      return 1
    fi

    echo "==> Multiple Harry Brain instances were discovered:"
    local i=1
    for line in "${discovered[@]}"; do
      printf '  %s) %s\n' "$i" "$line"
      i=$((i + 1))
    done
    echo "  m) Enter a Brain address manually"
    read -r -p "Choose a Brain [1]: " choice || true
    choice="${choice:-1}"
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#discovered[@]}" ]; then
      HARRY_BASE_URL="${discovered[$((choice - 1))]}"
      HARRY_INGEST_URL="${HARRY_BASE_URL%/}/ingest"
      echo "==> Using discovered Harry Brain at ${HARRY_BASE_URL}"
      return 0
    fi

    prompt_manual_brain_url
    return $?
  fi

  prompt_manual_brain_url
}

EXISTING_BASE_URL="$(current_configured_base_url "$PLATFORM" "$INSTALL_ROOT" || true)"
if [ -n "${HARRY_BASE_URL:-}" ] && [ -n "${EXISTING_BASE_URL:-}" ] && [ "${EXISTING_BASE_URL%/}" != "${HARRY_BASE_URL%/}" ]; then
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

if ! resolve_brain_url; then
  exit 1
fi

if [ -n "${EXISTING_BASE_URL:-}" ] && [ -n "${HARRY_BASE_URL:-}" ] && [ "${EXISTING_BASE_URL%/}" != "${HARRY_BASE_URL%/}" ]; then
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

fetch_agent_script() {
  local source_desc=""

  if [ -n "${HARRY_BASE_URL:-}" ]; then
    echo "==> Downloading Harry agent from ${HARRY_BASE_URL}/dist/harry_agent.sh"
    if curl -fsSL "${HARRY_BASE_URL}/dist/harry_agent.sh" -o "$TMP_AGENT"; then
      return 0
    fi
    echo "WARNING: Could not download Harry agent from Brain. Trying local fallbacks..." >&2
  fi

  if [ -f "$PACKAGED_AGENT_SCRIPT" ]; then
    source_desc="$PACKAGED_AGENT_SCRIPT"
  elif [ -f "$DEV_AGENT_SCRIPT" ]; then
    source_desc="$DEV_AGENT_SCRIPT"
  fi

  if [ -n "$source_desc" ]; then
    echo "==> Installing Harry agent from ${source_desc}"
    cp "$source_desc" "$TMP_AGENT"
    return 0
  fi

  echo "ERROR: Could not obtain the Harry agent script." >&2
  echo "Tried Brain download, packaged script at $PACKAGED_AGENT_SCRIPT, and repo checkout at $DEV_AGENT_SCRIPT." >&2
  echo "Ensure the Brain is reachable or stage harry_agent.sh alongside install-agent.sh." >&2
  return 1
}

if ! fetch_agent_script; then
  rm -f "$TMP_AGENT" >/dev/null 2>&1 || true
  exit 1
fi

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

RUNNER_PATH="${INSTALL_ROOT%/}/run-harry-agent.sh"
CONFIG_PATH="${INSTALL_ROOT%/}/harry-agent.env"

write_synology_bundle() {
  install -d -m 0755 "$INSTALL_ROOT" "$AGENT_DIR" "${INSTALL_ROOT%/}/logs" "${INSTALL_ROOT%/}/status" "${INSTALL_ROOT%/}/cache"

  cat > "$CONFIG_PATH" <<EOF_CONFIG
HARRY_BACKOFF_ENABLE=0
HARRY_SELF_UPDATE=0
HARRY_AGENT_DIR=${AGENT_DIR}
HARRY_STATUS_DIR=${INSTALL_ROOT%/}/status
HARRY_STATUS_FILE=${INSTALL_ROOT%/}/status/status.json
HARRY_LOG_FILE=${INSTALL_ROOT%/}/logs/harry-agent.log
HARRY_BRAIN_URL_CACHE_FILE=${INSTALL_ROOT%/}/cache/brain_url.txt
EOF_CONFIG

  if [ -n "${HARRY_BASE_URL:-}" ]; then
    cat >> "$CONFIG_PATH" <<EOF_CONFIG
HARRY_PUBLIC_BASE_URL=${HARRY_BASE_URL}
HARRY_BASE_URL=${HARRY_BASE_URL}
HARRY_INGEST_URL=${HARRY_BASE_URL}/ingest
EOF_CONFIG
  fi

  cat > "$RUNNER_PATH" <<'EOF_RUNNER'
#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/harry-agent.env"

if [ -f "$CONFIG_FILE" ]; then
  set -a
  . "$CONFIG_FILE"
  set +a
fi

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/syno/bin:/usr/syno/sbin"
exec "${SCRIPT_DIR}/agent/harry_agent.sh" "$@"
EOF_RUNNER

  chmod 0755 "$RUNNER_PATH" "$AGENT_PATH" >/dev/null 2>&1 || true
}

print_synology_instructions() {
  local run_cmd="${RUNNER_PATH}"

  echo
  echo "✅ Harry Agent installed for Synology DSM."
  echo "Agent:  ${AGENT_PATH}"
  echo "Config: ${CONFIG_PATH}"
  echo "Wrapper: ${RUNNER_PATH}"
  echo
  echo "DSM Task Scheduler:"
  echo "Control Panel > Task Scheduler > Create > Scheduled Task > User-defined script"
  echo "Run the task as the install owner, usually root when installed with sudo."
  echo "Synology self-update is disabled by default for safety."
  echo "Paste this script:"
  echo 'export PATH=/usr/local/bin:/usr/bin:/bin:/usr/syno/bin:/usr/syno/sbin'
  printf 'exec "%s"\n' "$run_cmd"
  echo
  echo "One-shot test:"
  printf '"%s"\n' "$run_cmd"
}

install_synology_mode() {
  echo "==> Installing Synology DSM-friendly agent bundle"
  write_synology_bundle
  print_synology_instructions
}

install_systemd_mode() {
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
ExecStart=${AGENT_PATH}
SuccessExitStatus=0
EOF_UNIT

  if [ -n "${HARRY_BASE_URL:-}" ]; then
    cat >> /etc/systemd/system/harry-agent.service <<EOF_UNIT
Environment="HARRY_PUBLIC_BASE_URL=${HARRY_BASE_URL}"
Environment="HARRY_BASE_URL=${HARRY_BASE_URL}"
Environment="HARRY_INGEST_URL=${HARRY_BASE_URL}/ingest"
EOF_UNIT
  fi

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

  echo "==> Enabling harry-agent.timer"
  systemctl enable harry-agent.timer

  echo "==> Starting harry-agent.timer"
  systemctl start harry-agent.timer

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
}

if [ "$PLATFORM" = "synology-dsm" ]; then
  install_synology_mode
else
  install_systemd_mode
fi
