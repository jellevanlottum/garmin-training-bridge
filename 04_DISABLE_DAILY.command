#!/bin/zsh
APP="$HOME/Library/Application Support/GarminTrainingBridge"
"$APP/.venv/bin/python" "$APP/scheduler.py" uninstall
read -r "x?Enter to close... "
