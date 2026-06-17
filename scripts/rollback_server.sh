#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-${DEPLOY_PATH:-/opt/temu_listing_workbench}}"
SERVICE_NAME="${SERVICE_NAME:-temu-workbench}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CURRENT_LINK="${DEPLOY_ROOT}/current"
RELEASES_DIR="${DEPLOY_ROOT}/releases"

log() {
  printf '[rollback] %s\n' "$*"
}

usage() {
  cat <<EOF
Usage:
  DEPLOY_ROOT=${DEPLOY_ROOT} bash scripts/rollback_server.sh --list
  DEPLOY_ROOT=${DEPLOY_ROOT} bash scripts/rollback_server.sh <release_id>

Examples:
  bash ${CURRENT_LINK}/scripts/rollback_server.sh --list
  bash ${CURRENT_LINK}/scripts/rollback_server.sh 20260617170000-45e555d
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

list_releases() {
  if [ ! -d "$RELEASES_DIR" ]; then
    echo "No releases directory: $RELEASES_DIR"
    return
  fi

  local current_target
  current_target="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f %p\n' |
    sort -rn |
    while read -r _mtime release_id release_path; do
      local marker=''
      if [ "$(readlink -f "$release_path")" = "$current_target" ]; then
        marker='*'
      fi
      local sha='unknown'
      local deployed_at='unknown'
      if [ -f "$release_path/.release" ]; then
        sha="$(awk -F= '$1=="source_sha"{print $2}' "$release_path/.release" | head -n 1)"
        deployed_at="$(awk -F= '$1=="deployed_at"{print $2}' "$release_path/.release" | head -n 1)"
      fi
      printf '%s %-28s sha=%s deployed_at=%s\n' "$marker" "$release_id" "${sha:-unknown}" "${deployed_at:-unknown}"
    done
}

health_check() {
  for attempt in $(seq 1 30); do
    if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" >/dev/null; then
      curl -fsS "http://127.0.0.1/" >/dev/null
      return
    fi
    sleep 1
  done
  systemctl status "$SERVICE_NAME" --no-pager -l >&2 || true
  journalctl -u "$SERVICE_NAME" -n 120 --no-pager >&2 || true
  exit 1
}

main() {
  require_command find
  require_command sort
  require_command readlink
  require_command systemctl
  require_command curl

  local target="${1:-}"
  if [ -z "$target" ] || [ "$target" = "-h" ] || [ "$target" = "--help" ]; then
    usage
    exit 0
  fi
  if [ "$target" = "--list" ] || [ "$target" = "list" ]; then
    list_releases
    exit 0
  fi

  local release_dir
  if [[ "$target" = /* ]]; then
    release_dir="$target"
  else
    release_dir="${RELEASES_DIR}/${target}"
  fi

  if [ ! -d "$release_dir" ]; then
    echo "Release not found: $release_dir" >&2
    list_releases >&2 || true
    exit 1
  fi
  if [ ! -f "$release_dir/backend/app/main.py" ]; then
    echo "Invalid release directory: $release_dir" >&2
    exit 1
  fi
  if [ ! -d "$release_dir/frontend/dist" ]; then
    echo "Release has no built frontend dist: $release_dir" >&2
    echo "Deploy that release once before rolling back to it." >&2
    exit 1
  fi

  log "Switching current to $release_dir"
  ln -sfnT "$release_dir" "$CURRENT_LINK"
  systemctl restart "$SERVICE_NAME"
  systemctl reload nginx || systemctl restart nginx || true
  health_check
  log "Rollback finished"
}

main "$@"
