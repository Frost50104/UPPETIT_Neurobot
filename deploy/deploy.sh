#!/usr/bin/env bash
# ── Deploy Neurobot to staging or production ─────────────────────────────
#
# Usage:
#   ./deploy/deploy.sh staging          # deploy to test.uppetitgpt.ru
#   ./deploy/deploy.sh prod             # deploy to uppetitgpt.ru
#   ./deploy/deploy.sh staging backend  # deploy only backend
#   ./deploy/deploy.sh staging frontend # deploy only frontend
#   ./deploy/deploy.sh prod backend     # deploy only backend to prod

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

CREDS_FILE="$HOME/.neurobot-deploy"
if [[ -f "$CREDS_FILE" ]]; then
    source "$CREDS_FILE"
fi

SERVER_HOST="${SERVER_HOST:-2.27.47.154}"
SERVER_USER="${SERVER_USER:-root}"
SSHPASS="/opt/homebrew/bin/sshpass"

if [[ -z "${SERVER_PASS:-}" ]]; then
    echo "ERROR: SERVER_PASS not set."
    echo "Create $CREDS_FILE with: SERVER_PASS=your_password"
    echo "Or set SERVER_PASS env variable."
    exit 1
fi

ENV="${1:-}"
COMPONENT="${2:-all}"  # "all", "backend", "frontend"

if [[ "$ENV" != "staging" && "$ENV" != "prod" ]]; then
    echo "Usage: $0 <staging|prod> [backend|frontend|all]"
    exit 1
fi

if [[ "$ENV" == "prod" ]]; then
    REMOTE_DIR="/opt/neurobot"
    SERVICE_NAME="neurobot"
    BUILD_MODE="production"
    PORT=8001
else
    REMOTE_DIR="/opt/neurobot-staging"
    SERVICE_NAME="neurobot-staging"
    BUILD_MODE="staging"
    PORT=8002
fi

SSH_CMD="$SSHPASS -p $SERVER_PASS ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST"
SCP_CMD="$SSHPASS -p $SERVER_PASS scp -o StrictHostKeyChecking=no"
RSYNC_CMD="$SSHPASS -p $SERVER_PASS rsync -az --delete -e 'ssh -o StrictHostKeyChecking=no'"

echo "=== Deploying [$ENV] ($COMPONENT) ==="
echo "  Remote: $SERVER_USER@$SERVER_HOST:$REMOTE_DIR"
echo "  Service: $SERVICE_NAME (port $PORT)"
echo ""

# ── Backend ──────────────────────────────────────────────────────────────
deploy_backend() {
    echo ">> Syncing backend..."
    eval "$RSYNC_CMD" \
        --exclude='.venv' \
        --exclude='.env' \
        --exclude='__pycache__' \
        --exclude='storage/' \
        --exclude='kb_images/' \
        --exclude='kb_downloads/' \
        --exclude='google_creds.json' \
        --exclude='alembic/versions/__pycache__' \
        "$PROJECT_DIR/backend/" "$SERVER_USER@$SERVER_HOST:$REMOTE_DIR/backend/"

    echo ">> Installing Python dependencies..."
    $SSH_CMD "cd $REMOTE_DIR/backend && .venv/bin/pip install -r requirements.txt -q"

    echo ">> Restarting $SERVICE_NAME..."
    $SSH_CMD "systemctl restart $SERVICE_NAME"

    echo ">> Backend deployed. Checking status..."
    sleep 2
    $SSH_CMD "systemctl is-active $SERVICE_NAME && echo 'Service is running' || echo 'WARNING: Service failed to start!'"
}

# ── Frontend ─────────────────────────────────────────────────────────────
deploy_frontend() {
    echo ">> Building frontend (mode=$BUILD_MODE)..."
    cd "$PROJECT_DIR/frontend"
    npm run build -- --mode "$BUILD_MODE"

    echo ">> Syncing frontend dist..."
    eval "$RSYNC_CMD" \
        "$PROJECT_DIR/frontend/dist/" "$SERVER_USER@$SERVER_HOST:$REMOTE_DIR/frontend/dist/"

    echo ">> Restarting $SERVICE_NAME (to pick up new sw.js)..."
    $SSH_CMD "systemctl restart $SERVICE_NAME"

    echo ">> Frontend deployed."
}

# ── Deploy config files ─────────────────────────────────────────────────
deploy_config() {
    echo ">> Syncing deploy configs..."
    eval "$RSYNC_CMD" \
        "$PROJECT_DIR/deploy/" "$SERVER_USER@$SERVER_HOST:$REMOTE_DIR/deploy/"
}

# ── Write VERSION file ─────────────────────────────────────────────────
write_version() {
    local hash dirty="" ts
    hash=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    if ! git -C "$PROJECT_DIR" diff --quiet 2>/dev/null; then
        dirty="-dirty"
    fi
    ts=$(date +%Y%m%d-%H%M%S)
    local ver="${hash}${dirty}-${ts}"
    echo "$ver" > "$PROJECT_DIR/backend/VERSION"
    echo "{\"version\":\"$ver\"}" > "$PROJECT_DIR/frontend/public/version.json"
    echo ">> VERSION=$ver"
}

# ── Execute ──────────────────────────────────────────────────────────────
write_version
deploy_config

case "$COMPONENT" in
    backend)  deploy_backend ;;
    frontend) deploy_frontend ;;
    all)      deploy_backend; deploy_frontend ;;
    *)        echo "Unknown component: $COMPONENT"; exit 1 ;;
esac

echo ""
echo "=== Deploy [$ENV] complete! ==="
if [[ "$ENV" == "staging" ]]; then
    echo "  URL: https://test.uppetitgpt.ru"
else
    echo "  URL: https://uppetitgpt.ru"
fi
echo "  Logs: ssh $SERVER_USER@$SERVER_HOST journalctl -u $SERVICE_NAME -f"
