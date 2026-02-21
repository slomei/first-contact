#!/usr/bin/env bash
set -e

# Colors (if terminal supports them)
if [ -t 1 ]; then
    GREEN='\033[32m'
    RED='\033[31m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN='' RED='' BOLD='' RESET=''
fi

ok()  { echo -e "${GREEN}$1${RESET}"; }
err() { echo -e "${RED}$1${RESET}"; }

cd "$(dirname "$0")"
echo -e "${BOLD}First Contact — Setup${RESET}"
echo ""

# 1. Python version check
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err "Error: Python 3 not found."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    err "Error: Python 3.10+ is required. Found: $PY_VERSION"
    exit 1
fi
ok "Python $PY_VERSION found."

# 2. Create virtual environment
if [ -d "venv" ]; then
    echo "Virtual environment already exists, skipping."
else
    echo "Creating virtual environment..."
    "$PYTHON" -m venv venv
    ok "Virtual environment created."
fi

# 3. Install dependencies
echo "Installing dependencies..."
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt -q
ok "Dependencies installed."

# 4. Copy config templates
if [ -f ".env" ]; then
    echo ".env already exists, skipping."
else
    cp .env.example .env
    ok "Created .env from template."
fi

if [ -f "config.json" ]; then
    echo "config.json already exists, skipping."
else
    cp config.example.json config.json
    ok "Created config.json from template."
fi

# 5. Done
echo ""
ok "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add your Anthropic API key to .env"
echo "  2. (Optional) Add Discord/Telegram tokens to .env"
echo "  3. Run: source venv/bin/activate && python chat.py"
echo ""
echo "The onboarding wizard will guide you through the rest on first launch."
