#!/bin/bash
# Skylight Photos deployment script for webserver-50
set -e

APP_DIR="/opt/skylight-photos"
VENV_DIR="$APP_DIR/venv"

echo "=== Skylight Photos Deployment ==="

# Pull latest code from git
echo "Pulling latest code..."
git -C "$(dirname "$0")/.." pull

# Create app directory
sudo mkdir -p "$APP_DIR"
sudo chown user:user "$APP_DIR"

# Copy files
echo "Copying files..."
rsync -av --exclude='venv' --exclude='__pycache__' --exclude='.git' --exclude='uploads' \
    ./ "$APP_DIR/"

# Create uploads directory
mkdir -p "$APP_DIR/uploads"

# Python venv + deps
echo "Setting up Python environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

# Setup config
if [ ! -f "$APP_DIR/config/settings.json" ]; then
    echo "Creating settings.json from example..."
    cp "$APP_DIR/config/settings.example.json" "$APP_DIR/config/settings.json"
    echo ">>> EDIT $APP_DIR/config/settings.json to set your PIN <<<"
fi

# Install systemd service
echo "Installing systemd service..."
sudo cp "$APP_DIR/deploy/skylight-photos-api.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable skylight-photos-api
sudo systemctl restart skylight-photos-api

# Install nginx config
echo "Installing nginx config..."
sudo cp "$APP_DIR/deploy/nginx-photos.2azone.com.conf" /etc/nginx/sites-available/photos.2azone.com
sudo ln -sf /etc/nginx/sites-available/photos.2azone.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# SSL certificate
if [ ! -f /etc/letsencrypt/live/photos.2azone.com/fullchain.pem ]; then
    echo "Getting Let's Encrypt certificate..."
    sudo certbot --nginx -d photos.2azone.com --non-interactive --agree-tos -m admin@2azone.com
fi

echo ""
echo "=== Deployment Complete ==="
echo "Service: sudo systemctl status skylight-photos-api"
echo "Logs:    sudo journalctl -u skylight-photos-api -f"
echo "URL:     https://photos.2azone.com"
