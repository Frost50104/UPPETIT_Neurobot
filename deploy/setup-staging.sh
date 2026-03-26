#!/usr/bin/env bash
# ── One-time setup of the staging environment on the server ──────────────
# Run this script ON the server (via SSH) once to create the staging env.
#
# Prerequisites:
#   - Production already deployed at /opt/neurobot
#   - PostgreSQL, Redis, Nginx, certbot installed
#
# Usage:
#   bash /opt/neurobot/deploy/setup-staging.sh

set -euo pipefail

STAGING_DIR="/opt/neurobot-staging"
PROD_DIR="/opt/neurobot"

echo "=== Setting up Neurobot staging environment ==="

# 1. Clone the project (or copy from prod)
if [ ! -d "$STAGING_DIR" ]; then
    echo ">> Copying project to $STAGING_DIR..."
    cp -r "$PROD_DIR" "$STAGING_DIR"
else
    echo ">> $STAGING_DIR already exists, skipping copy."
fi

# 2. Create staging database
echo ">> Creating staging database..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'neurobot_staging_db'" \
  | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE neurobot_staging_db OWNER neurobot_user;"
echo "   Database ready."

# 3. Create Python venv for staging
echo ">> Setting up Python venv..."
cd "$STAGING_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
echo "   Venv ready."

# 4. Create staging .env from example
if [ ! -f "$STAGING_DIR/backend/.env" ]; then
    echo ">> Creating staging .env..."
    cp "$STAGING_DIR/backend/.env.staging.example" "$STAGING_DIR/backend/.env"
    echo "   !!! EDIT $STAGING_DIR/backend/.env with real values (SECRET_KEY, OPENAI_API_KEY, etc.) !!!"
else
    echo ">> $STAGING_DIR/backend/.env already exists, skipping."
fi

# 5. Copy Google credentials
if [ ! -f "$STAGING_DIR/backend/google_creds.json" ] && [ -f "$PROD_DIR/backend/google_creds.json" ]; then
    echo ">> Copying Google credentials..."
    cp "$PROD_DIR/backend/google_creds.json" "$STAGING_DIR/backend/google_creds.json"
fi

# 6. Install systemd service
echo ">> Installing systemd service..."
cp "$STAGING_DIR/deploy/systemd/neurobot-staging.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable neurobot-staging
echo "   Service installed."

# 7. Install nginx config
echo ">> Installing nginx config..."
cp "$STAGING_DIR/deploy/nginx/neurobot-staging.conf" /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/neurobot-staging.conf /etc/nginx/sites-enabled/
echo "   Nginx config installed."

# 8. SSL certificate for test.uppetitgpt.ru
echo ">> Requesting SSL certificate for test.uppetitgpt.ru..."
echo "   Make sure DNS A record for test.uppetitgpt.ru points to this server first!"
echo "   Run: certbot --nginx -d test.uppetitgpt.ru"
echo ""

# 9. Build frontend for staging
echo ">> Building frontend for staging..."
cd "$STAGING_DIR/frontend"
npm install
npm run build:staging
echo "   Frontend built."

# 10. Start staging
echo ">> Starting staging..."
systemctl start neurobot-staging
nginx -t && systemctl reload nginx
echo ""
echo "=== Staging setup complete! ==="
echo "  URL:     https://test.uppetitgpt.ru"
echo "  Backend: /opt/neurobot-staging/backend (port 8002)"
echo "  Service: systemctl {start|stop|restart|status} neurobot-staging"
echo "  Logs:    journalctl -u neurobot-staging -f"
echo ""
echo "  Don't forget to:"
echo "  1. Edit $STAGING_DIR/backend/.env with real SECRET_KEY and OPENAI_API_KEY"
echo "  2. Set up DNS A record for test.uppetitgpt.ru"
echo "  3. Run: certbot --nginx -d test.uppetitgpt.ru"
echo "  4. Rebuild KB on staging: curl -X POST https://test.uppetitgpt.ru/api/admin/kb/refresh"
