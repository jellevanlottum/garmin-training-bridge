#!/bin/zsh
APP="$HOME/Library/Application Support/GarminTrainingBridge"
"$APP/.venv/bin/python" "$APP/scheduler.py" install
read -r "x?Enter to close... "
