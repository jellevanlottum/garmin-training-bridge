#!/bin/zsh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
APP="$HOME/Library/Application Support/GarminTrainingBridge"
MODE="${1:---automatic}"
exec "$APP/.venv/bin/python" "$APP/pipeline.py" --mode "${MODE#--}"
