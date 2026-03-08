# `piailot:ai`

Self-hosted AI chat gateway powered by OpenRouter free models.

PiAiLot is a lightweight, self-hosted AI chat interface designed to run on minimal hardware like a Raspberry Pi. It connects to OpenRouter's free AI models, providing a multi-user chat platform with PIN-based authentication, customizable AI skills, and a built-in admin panel -- all wrapped in a clean terminal aesthetic.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

## Features

- **Multi-user PIN authentication** -- each user gets a unique PIN code, no passwords or accounts to manage
- **AI skills system** -- create custom system prompts that shape AI behaviour for different tasks
- **Built-in tools** -- web search, calculator, and other utilities available to the AI
- **Admin panel** -- manage users, skills, and system settings from a web interface
- **Auto-failover** -- automatically cycles through free models if one is unavailable
- **Streaming responses** -- real-time token streaming for responsive conversations
- **Lightweight** -- runs comfortably on 1GB RAM (Raspberry Pi, VPS, etc.)
- **Terminal aesthetic** -- clean, monospace UI with a hacker-friendly feel

## Quick Start

On a fresh Linux machine (Raspberry Pi OS, Ubuntu, Debian):

```bash
curl -sSL https://raw.githubusercontent.com/LSDLabsHQ/piailot/main/install.sh | bash
```

The installer will prompt for your OpenRouter API key and handle everything else.

## Requirements

- Linux (Raspberry Pi OS, Ubuntu, Debian, etc.)
- Python 3.11+
- nginx
- git

## Manual Install

```bash
# Clone the repository
git clone https://github.com/LSDLabsHQ/piailot.git
cd piailot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env   # or create .env manually
```

Create a `.env` file with:

```
OPENROUTER_API_KEY=your-api-key-here
SESSION_SECRET=your-random-secret-here
```

Generate a session secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Run the development server:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key ([get one here](https://openrouter.ai/keys)) | Yes |
| `SESSION_SECRET` | Random hex string for session signing | Yes |

### Remote Access with Tailscale

For secure remote access without exposing ports to the internet, consider using [Tailscale](https://tailscale.com/):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Your device will be accessible at `http://<tailscale-hostname>` from any device on your Tailscale network.

## Usage

### Creating Users

Users are managed through the admin panel. Each user is assigned a unique PIN code that they use to log in. User data is stored as JSON files in the `users/` directory.

### Skills

Skills are custom system prompts that change how the AI behaves. You can create skills for specific tasks like coding, writing, translation, or analysis. Skills are managed through the admin panel or the skills page.

### Admin Panel

To promote a user to admin, use the following command:

```bash
cd ~/piailot  # or your install directory
python3 -c "
import json
with open('users/YOUR_USERNAME/profile.json') as f:
    p = json.load(f)
p['is_admin'] = True
with open('users/YOUR_USERNAME/profile.json', 'w') as f:
    json.dump(p, f, indent=2)
print('Done')
"
```

Replace `YOUR_USERNAME` with the user's directory name (lowercase, hyphenated). Once promoted, the admin panel link appears in the sidebar.

## Managing the Service

If installed via `install.sh`, the service is managed with systemd:

```bash
# Start the service
sudo systemctl start piailot

# Stop the service
sudo systemctl stop piailot

# Restart the service
sudo systemctl restart piailot

# View logs
sudo journalctl -u piailot -f

# Check status
sudo systemctl status piailot
```

## Uninstall

To remove piailot completely:

```bash
~/piailot/uninstall.sh
```

Or specify a custom install directory:

```bash
bash uninstall.sh /path/to/piailot
```

This will stop the service, remove systemd and nginx configs, and delete the install directory.

## Contributing

Contributions welcome! Please open an issue first to discuss what you would like to change.

## License

[MIT](LICENSE)
