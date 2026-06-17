#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-${DEPLOY_PATH:-/opt/temu_listing_workbench}}"
APP_DIR="${DEPLOY_PATH:-${DEPLOY_ROOT}/current}"
REPO_URL="${REPO_URL:-https://github.com/napawam913-byte/temu_listing_workbench.git}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-temu-workbench}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CURRENT_LINK="${DEPLOY_ROOT}/current"
RELEASES_DIR="${DEPLOY_ROOT}/releases"
SHARED_DIR="${DEPLOY_ROOT}/shared"
SHARED_ENV="${SHARED_DIR}/.env"
SHARED_STORAGE_DIR="${SHARED_DIR}/storage"
SHARED_BACKEND_RUNTIME_DIR="${SHARED_DIR}/backend_runtime"
LEGACY_ENV="${DEPLOY_ROOT}/.env"

log() {
  printf '[deploy] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

require_command node
require_command python3
require_command npm
require_command systemctl
require_command nginx
require_command curl

print_service_debug() {
  echo "----- systemctl status ${SERVICE_NAME} -----" >&2
  systemctl status "$SERVICE_NAME" --no-pager -l >&2 || true
  echo "----- journalctl ${SERVICE_NAME} -----" >&2
  journalctl -u "$SERVICE_NAME" -n 120 --no-pager >&2 || true
}

NODE_MAJOR="$(node -p "Number(process.versions.node.split('.')[0])")"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Node.js 18+ is required for the frontend build. Current: $(node --version)" >&2
  exit 1
fi

if [ "${SKIP_GIT_PULL:-0}" = "1" ]; then
  log "Using uploaded release in ${APP_DIR}"
else
  require_command git
  mkdir -p "$APP_DIR"
  cd "$APP_DIR"
  if [ ! -d "$APP_DIR/.git" ]; then
    log "Initialising ${APP_DIR}"
    git init
    git remote add origin "$REPO_URL" 2>/dev/null || git remote set-url origin "$REPO_URL"
  fi
  log "Pulling ${BRANCH}"
  git fetch origin "$BRANCH"
  git checkout -B "$BRANCH" "origin/$BRANCH"
  git pull --ff-only origin "$BRANCH"
fi

mkdir -p "$RELEASES_DIR" "$SHARED_DIR" "$SHARED_STORAGE_DIR" "$SHARED_BACKEND_RUNTIME_DIR"

if [ ! -f "$SHARED_ENV" ] && [ -f "$LEGACY_ENV" ]; then
  log "Migrating legacy env file to ${SHARED_ENV}"
  cp "$LEGACY_ENV" "$SHARED_ENV"
fi

if [ ! -f "$SHARED_ENV" ] && [ -f "$APP_DIR/.env" ]; then
  log "Moving release env file to ${SHARED_ENV}"
  cp "$APP_DIR/.env" "$SHARED_ENV"
fi

if [ ! -f "$SHARED_ENV" ]; then
  cat >&2 <<EOF
Missing $SHARED_ENV
Create it on the server before deploying. Do not commit secrets to Git.
EOF
  exit 1
fi

if [ -d "$APP_DIR/storage/templates" ] && [ ! -L "$APP_DIR/storage" ]; then
  mkdir -p "$SHARED_STORAGE_DIR/templates"
  cp -a "$APP_DIR/storage/templates/." "$SHARED_STORAGE_DIR/templates/"
fi
if [ -e "$APP_DIR/storage" ] || [ -L "$APP_DIR/storage" ]; then
  rm -rf "$APP_DIR/storage"
fi
ln -sfn "$SHARED_STORAGE_DIR" "$APP_DIR/storage"
ln -sfn "$SHARED_ENV" "$APP_DIR/.env"

if [ -e "$APP_DIR/backend/runtime" ] || [ -L "$APP_DIR/backend/runtime" ]; then
  rm -rf "$APP_DIR/backend/runtime"
fi
ln -sfn "$SHARED_BACKEND_RUNTIME_DIR" "$APP_DIR/backend/runtime"

log "Installing backend dependencies"
cd "$APP_DIR/backend"
python3 -m venv .venv
. "$APP_DIR/backend/.venv/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements.txt

log "Building frontend"
cd "$APP_DIR/frontend"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build

log "Activating release"
if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
  mv "$CURRENT_LINK" "${CURRENT_LINK}.legacy.$(date -u +%Y%m%d%H%M%S)"
fi
ln -sfnT "$APP_DIR" "$CURRENT_LINK"
{
  printf 'release_id=%s\n' "${RELEASE_ID:-$(basename "$APP_DIR")}"
  printf 'source_sha=%s\n' "${SOURCE_SHA:-unknown}"
  printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$APP_DIR/.release"

log "Writing systemd service"
cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Temu Listing Workbench API
After=network.target

[Service]
Type=simple
WorkingDirectory=${CURRENT_LINK}/backend
EnvironmentFile=${SHARED_ENV}
Environment=TEMU_WORKBENCH_BACKEND_DIR=${CURRENT_LINK}/backend
Environment=TEMU_WORKBENCH_PROJECT_ROOT=${CURRENT_LINK}
ExecStart=${CURRENT_LINK}/backend/.venv/bin/python -m uvicorn app.main:app --host ${BACKEND_HOST} --port ${BACKEND_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

log "Writing nginx site"
cat >"/etc/nginx/sites-available/${SERVICE_NAME}" <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 100m;
    root ${CURRENT_LINK}/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT}/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /docs {
        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT}/docs;
        proxy_set_header Host \$host;
    }

    location /openapi.json {
        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT}/openapi.json;
        proxy_set_header Host \$host;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

ln -sfn "/etc/nginx/sites-available/${SERVICE_NAME}" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx || systemctl restart nginx

log "Checking service health"
for attempt in $(seq 1 30); do
  if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    print_service_debug
    exit 1
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1/" >/dev/null

log "Deployment finished"
