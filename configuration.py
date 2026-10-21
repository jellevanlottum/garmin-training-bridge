#!/usr/bin/env python3
"""Local configuration stored OUTSIDE the shared source-code repository."""
import json
import os
from pathlib import Path
import re
import sys

APP = Path.home() / 'Library' / 'Application Support' / 'GarminTrainingBridge'
CONFIG_FILE = APP / 'config.json'
REPO_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def validate(conf):
    repo = str(conf.get('data_repository', '')).strip()
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError('Repository must be in OWNER/REPOSITORY format.')
    data_home = Path(str(conf.get('training_directory', '~/GarminTraining'))).expanduser()
    if not data_home.is_absolute():
        raise ValueError('Training directory must be an absolute path.')
    recent = int(conf.get('recent_runs', 30))
    streams = int(conf.get('recent_streams', 20))
    if not (1 <= recent <= 100 and 1 <= streams <= 50):
        raise ValueError('recent_runs 1–100; recent_streams 1–50.')
    return {'data_repository': repo, 'training_directory': str(data_home),
            'recent_runs': recent, 'recent_streams': streams}


def load():
    if not CONFIG_FILE.exists():
        raise RuntimeError('Missing configuration; run 01_INSTALL.command first.')
    return validate(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))


def configure():
    APP.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(APP, 0o700)
    existing = {}
    if CONFIG_FILE.exists():
        try:
            existing = load()
        except Exception:
            pass
    print('Garmin Training Bridge - local setup (nothing is uploaded here)')
    print('First create an EMPTY, PRIVATE GitHub repository for your data.')
    default = existing.get('data_repository', '')
    while True:
        prompt = f'Data repository (OWNER/NAME){f" [{default}]" if default else ""}: '
        repo = input(prompt).strip() or default
        if REPO_PATTERN.fullmatch(repo):
            break
        print('Example: alexrunner/my-private-garmin')
    location = existing.get('training_directory', str(Path.home() / 'GarminTraining'))
    specified = input(f'Local Garmin training directory [{location}]: ').strip() or location
    selected = validate({'data_repository': repo, 'training_directory': specified,
                         'recent_runs': existing.get('recent_runs', 30),
                         'recent_streams': existing.get('recent_streams', 20)})
    tmp = CONFIG_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(selected, indent=2) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)
    print(f'Saved configuration locally to: {CONFIG_FILE}')
    print('No passwords or tokens are included in this configuration.')

if __name__ == '__main__':
    configure()
