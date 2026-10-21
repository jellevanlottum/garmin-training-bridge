#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
APP="$HOME/Library/Application Support/GarminTrainingBridge"
"$APP/.venv/bin/python" "$APP/pipeline.py" --history
rc=$?
read -r "x?Enter to close... "
exit $rc
