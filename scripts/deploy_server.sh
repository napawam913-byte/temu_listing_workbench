#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${DEPLOY_PATH:-/opt/temu_listing_workbench}"
REPO_URL="${REPO_URL:-https://github.com/napawam913-byte/temu_listing_workbench.git}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-temu-workbench}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

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

if [ ! -f "$APP_DIR/.env" ]; then
  cat >&2 <<EOF
Missing $APP_DIR/.env
Create it on the server before deploying. Do not commit secrets to Git.
EOF
  exit 1
fi

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

log "Writing systemd service"
cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Temu Listing Workbench API
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/backend/.venv/bin/python -m uvicorn app.main:app --host ${BACKEND_HOST} --port ${BACKEND_PORT}
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
    root ${APP_DIR}/frontend/dist;
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
curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/docs" >/dev/null
curl -fsS "http://127.0.0.1/" >/dev/null

log "Deployment finished"
