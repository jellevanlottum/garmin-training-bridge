#!/bin/zsh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")"
APP="$HOME/Library/Application Support/GarminTrainingBridge"
mkdir -p "$APP"; chmod 700 "$APP"
PYTHON=""
for p in python3.14 python3.13 python3.12 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys;sys.exit(sys.version_info < (3,12))'; then
    PYTHON="$(command -v "$p")"; break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.12+ required. Get it from https://www.python.org/downloads/macos/."; read -r "x?Enter to close... "; exit 1
fi
cp configuration.py pipeline.py garmin_sync.py garmin_history.py export_training.py scheduler.py run.sh requirements.txt "$APP/"
chmod 700 "$APP/run.sh"
if [[ ! -x "$APP/.venv/bin/python" ]]; then "$PYTHON" -m venv "$APP/.venv"; fi
"$APP/.venv/bin/python" -m pip install -r "$APP/requirements.txt"
if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is not installed. Install using: brew install gh"
  echo "Install Homebrew first if needed: https://brew.sh/"
fi
"$APP/.venv/bin/python" "$APP/configuration.py"
echo "Installation complete. Start 02_FIRST_SYNC.command."
read -r "x?Enter to close... "
