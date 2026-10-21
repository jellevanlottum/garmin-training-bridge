#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
APP="$HOME/Library/Application Support/GarminTrainingBridge"
if [[ ! -x "$APP/.venv/bin/python" ]]; then echo "Run 01_INSTALL.command first"; exit 1; fi
"$APP/.venv/bin/python" "$APP/pipeline.py" --mode manual
rc=$?
echo "Return code: $rc"
read -r "x?Enter to close... "
exit $rc
