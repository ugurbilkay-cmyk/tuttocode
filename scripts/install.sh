#!/usr/bin/env bash
# One-command installer for Ubuntu 24.04.
#   bash install.sh https://github.com/<you>/<repo>.git
# Safe to run again to update.
set -euo pipefail

REPO="${1:?Usage: bash install.sh <git repo url>}"
APP=/opt/tpcode
DATA=/var/lib/tpcode
ENVF=/etc/tpcode.env

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3-venv python3-pip git curl caddy ufw openssl unattended-upgrades libgl1 libglib2.0-0

id tpcode >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin tpcode

echo "==> Getting the code"
if [ -d "$APP/.git" ]; then
  git -C "$APP" pull --ff-only
else
  git clone "$REPO" "$APP"
fi

echo "==> Python packages (takes a few minutes)"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "==> Face models"
[ -f "$APP/models/face_landmarker.task" ] || sh "$APP/scripts/download_models.sh"

mkdir -p "$DATA"
NEWPW=""
if [ ! -f "$ENVF" ]; then
  NEWPW="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 14)"
  cat > "$ENVF" <<EOF
SHORT_DOMAIN=tpcode.uk
PUBLIC_BASE_URL=https://staff.tpcode.uk
SHOP_NAME=Tuttoprint
SHOP_CONTACT="info@tuttoprint.co.uk · Edmonton Green, London"
ADMIN_USER=admin
ADMIN_PASSWORD=$NEWPW
RETENTION_DAYS=30
PENDING_RETENTION_HOURS=24
BG_REPLACE=false
PUBLIC_UPLOADS=false
DATA_DIR=$DATA
MODEL_DIR=$APP/models
EOF
  chmod 600 "$ENVF"
fi
chown -R tpcode:tpcode "$APP" "$DATA"

echo "==> App service"
cat > /etc/systemd/system/tpcode.service <<EOF
[Unit]
Description=Tuttoprint passport photo codes
After=network-online.target

[Service]
User=tpcode
WorkingDirectory=$APP
EnvironmentFile=$ENVF
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tpcode
systemctl restart tpcode

echo "==> Web server + HTTPS"
cp "$APP/Caddyfile.example" /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

echo "==> Firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

sleep 3
echo
if systemctl is-active --quiet tpcode; then echo "App:  RUNNING"; else echo "App:  NOT RUNNING — run: journalctl -u tpcode -n 50"; fi
echo "Open: https://staff.tpcode.uk/admin"
if [ -n "$NEWPW" ]; then
  echo
  echo "Login user:     admin"
  echo "Login password: $NEWPW"
  echo "WRITE THIS PASSWORD DOWN NOW."
fi
