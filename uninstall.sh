#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
#  piailot:ai uninstaller
# ─────────────────────────────────────────────

INSTALL_DIR="${1:-$HOME/piailot}"
# Expand tilde
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

echo ""
echo "  piailot:ai uninstaller"
echo "  ──────────────────────"
echo ""

# ── Check install directory exists ──────────

if [ ! -d "$INSTALL_DIR" ]; then
    echo "[!] Install directory not found: $INSTALL_DIR"
    echo "    Usage: $0 [install-directory]"
    exit 1
fi

# ── Show what will be removed ───────────────

echo "  The following will be removed:"
echo ""
echo "    - Systemd service:  /etc/systemd/system/piailot.service"
echo "    - Nginx config:     /etc/nginx/sites-available/piailot"
echo "    - Nginx symlink:    /etc/nginx/sites-enabled/piailot"
echo "    - Install directory: $INSTALL_DIR"
echo ""

read -rp "  Proceed with uninstall? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "[*] Uninstall cancelled."
    exit 0
fi

echo ""

# ── Stop and disable systemd service ────────

echo "[*] Stopping piailot service..."
if sudo systemctl is-active --quiet piailot 2>/dev/null; then
    sudo systemctl stop piailot
    echo "[+] Service stopped."
else
    echo "[+] Service was not running."
fi

if sudo systemctl is-enabled --quiet piailot 2>/dev/null; then
    sudo systemctl disable piailot
    echo "[+] Service disabled."
fi

if [ -f /etc/systemd/system/piailot.service ]; then
    sudo rm -f /etc/systemd/system/piailot.service
    sudo systemctl daemon-reload
    echo "[+] Service file removed."
fi

# ── Remove nginx config ────────────────────

echo "[*] Removing nginx configuration..."
if [ -f /etc/nginx/sites-enabled/piailot ]; then
    sudo rm -f /etc/nginx/sites-enabled/piailot
fi
if [ -f /etc/nginx/sites-available/piailot ]; then
    sudo rm -f /etc/nginx/sites-available/piailot
fi
sudo systemctl reload nginx 2>/dev/null || true
echo "[+] Nginx configuration removed."

# ── Delete install directory ────────────────

echo "[*] Removing install directory..."
rm -rf "$INSTALL_DIR"
echo "[+] Removed $INSTALL_DIR"

# ── Done ────────────────────────────────────

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │                                     │"
echo "  │   piailot:ai has been uninstalled   │"
echo "  │                                     │"
echo "  └─────────────────────────────────────┘"
echo ""
