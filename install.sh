#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
#  piailot:ai installer
#  Self-hosted AI chat gateway
# ─────────────────────────────────────────────

REPO_URL="https://github.com/LSDLabsHQ/piailot.git"

# Reattach stdin to terminal (needed for curl | bash)
if [ ! -t 0 ]; then
  exec < /dev/tty
fi

# ── Branded header ──────────────────────────

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │                                     │"
echo "  │        piailot:ai installer         │"
echo "  │                                     │"
echo "  │   Self-hosted AI chat gateway       │"
echo "  │   powered by OpenRouter free models │"
echo "  │                                     │"
echo "  └─────────────────────────────────────┘"
echo ""

# ── Pre-flight checks ──────────────────────

echo "[*] Running pre-flight checks..."
echo ""

MISSING=0

# Python 3.11+
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
        echo "  [!] Python $PY_VERSION found, but 3.11+ is required."
        echo "      sudo apt install python3.11  (Debian/Ubuntu)"
        MISSING=1
    else
        echo "  [+] Python $PY_VERSION"
    fi
else
    echo "  [!] python3 not found."
    echo "      sudo apt install python3  (Debian/Ubuntu)"
    MISSING=1
fi

# pip3
if command -v pip3 &>/dev/null; then
    echo "  [+] pip3"
else
    echo "  [!] pip3 not found."
    echo "      sudo apt install python3-pip  (Debian/Ubuntu)"
    MISSING=1
fi

# nginx
if command -v nginx &>/dev/null; then
    echo "  [+] nginx"
else
    echo "  [!] nginx not found."
    echo "      sudo apt install nginx  (Debian/Ubuntu)"
    MISSING=1
fi

# git
if command -v git &>/dev/null; then
    echo "  [+] git"
else
    echo "  [!] git not found."
    echo "      sudo apt install git  (Debian/Ubuntu)"
    MISSING=1
fi

echo ""

if [ "$MISSING" -ne 0 ]; then
    echo "[!] Missing dependencies. Install them and re-run this script."
    exit 1
fi

echo "[+] All pre-flight checks passed."
echo ""

# ── User prompts ────────────────────────────

read -rp "  OpenRouter API key: " API_KEY
if [ -z "$API_KEY" ]; then
    echo "[!] API key is required. Get one at https://openrouter.ai/keys"
    exit 1
fi

read -rp "  Install directory [~/piailot]: " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$HOME/piailot}"
# Expand tilde
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

read -rp "  Backend port [8000]: " PORT
PORT="${PORT:-8000}"

echo ""

# ── Clone repository ────────────────────────

if [ -d "$INSTALL_DIR" ]; then
    echo "[!] Directory $INSTALL_DIR already exists."
    read -rp "    Overwrite? [y/N]: " OVERWRITE
    if [[ "$OVERWRITE" =~ ^[Yy]$ ]]; then
        echo "[*] Removing existing directory..."
        rm -rf "$INSTALL_DIR"
    else
        echo "[!] Aborting. Remove the directory or choose a different path."
        exit 1
    fi
fi

echo "[*] Cloning repository to $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
echo ""

# ── Python virtual environment ──────────────

echo "[*] Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"

echo "[*] Installing dependencies..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
echo "[+] Dependencies installed."
echo ""

# ── Generate secrets and write .env ─────────

echo "[*] Generating session secret..."
SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

echo "[*] Writing .env file..."
cat > "$INSTALL_DIR/.env" <<EOF
OPENROUTER_API_KEY=$API_KEY
SESSION_SECRET=$SESSION_SECRET
EOF
chmod 600 "$INSTALL_DIR/.env"
echo "[+] .env written (permissions: 600)."
echo ""

# ── Create users directory ──────────────────

mkdir -p "$INSTALL_DIR/users"
echo "[+] Created users/ directory."

# ── Install systemd service ─────────────────

echo "[*] Installing systemd service..."
CURRENT_USER=$(whoami)

sed \
    -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    -e "s|__USER__|$CURRENT_USER|g" \
    -e "s|__PORT__|$PORT|g" \
    "$INSTALL_DIR/config/piailot.service" \
    | sudo tee /etc/systemd/system/piailot.service > /dev/null

echo "[+] Systemd service installed."

# ── Install nginx config ────────────────────

echo "[*] Configuring nginx..."

sed \
    -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    -e "s|__PORT__|$PORT|g" \
    "$INSTALL_DIR/config/piailot-nginx.conf" \
    | sudo tee /etc/nginx/sites-available/piailot > /dev/null

# Symlink to sites-enabled
sudo ln -sf /etc/nginx/sites-available/piailot /etc/nginx/sites-enabled/piailot

# Remove default site if it exists
if [ -f /etc/nginx/sites-enabled/default ]; then
    sudo rm -f /etc/nginx/sites-enabled/default
    echo "[+] Removed default nginx site."
fi

echo "[+] Nginx configured."
echo ""

# ── Fix permissions ─────────────────────────

echo "[*] Setting permissions..."
chmod 711 "$HOME"
chmod -R 755 "$INSTALL_DIR/static"
echo "[+] Permissions set."
echo ""

# ── Enable and start services ───────────────

echo "[*] Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable piailot.service
sudo systemctl start piailot.service
sudo systemctl reload nginx
echo "[+] Services started."
echo ""

# ── Success message ─────────────────────────

HOSTNAME_LOCAL="$(hostname).local"
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown")

echo "  ┌─────────────────────────────────────┐"
echo "  │                                     │"
echo "  │     piailot:ai is now running!      │"
echo "  │                                     │"
echo "  └─────────────────────────────────────┘"
echo ""
echo "  Access your instance at:"
echo ""
echo "    http://$HOSTNAME_LOCAL"
echo "    http://$IP_ADDR"
echo ""
echo "  ── Management Commands ───────────────"
echo ""
echo "    Start:    sudo systemctl start piailot"
echo "    Stop:     sudo systemctl stop piailot"
echo "    Restart:  sudo systemctl restart piailot"
echo "    Logs:     sudo journalctl -u piailot -f"
echo "    Config:   $INSTALL_DIR/.env"
echo ""
