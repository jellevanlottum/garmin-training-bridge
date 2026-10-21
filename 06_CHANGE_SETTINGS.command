#!/bin/zsh
APP="$HOME/Library/Application Support/GarminTrainingBridge"
"$APP/.venv/bin/python" "$APP/configuration.py"
read -r "x?Enter to close... "
