#!/usr/bin/env python3
"""Install a per-user macOS LaunchAgent for local Garmin to private GitHub sync."""
from pathlib import Path
import subprocess
import sys
import plistlib

NAME = 'org.community.garmin-training-bridge'
APP = Path.home() / 'Library' / 'Application Support' / 'GarminTrainingBridge'
FILE = Path.home() / 'Library' / 'LaunchAgents' / (NAME + '.plist')
LOG = Path.home() / 'Library' / 'Logs' / 'GarminTrainingBridge.log'


def launchctl(*args):
    return subprocess.run(['launchctl', *args], capture_output=True, text=True)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Automatische scheduling werkt alleen op macOS.')
    if len(sys.argv) < 2 or sys.argv[1] not in ('install', 'uninstall'):
        raise SystemExit('Gebruik: scheduler.py install|uninstall')
    uid = str(__import__('os').getuid())
    target = f'gui/{uid}'
    launchctl('bootout', target, str(FILE))
    if sys.argv[1] == 'uninstall':
        FILE.unlink(missing_ok=True)
        print('Dagelijkse Garmin Training Bridge synchronisatie uitgeschakeld.')
        return
    hour = input('Dagelijkse starttijd (HH:MM, Enter = 20:00): ').strip() or '20:00'
    try:
        h, m = map(int, hour.split(':'))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        raise SystemExit('Voer een geldige tijd in als HH:MM.')
    FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'Label': NAME,
        'ProgramArguments': ['/bin/zsh', str(APP / 'run.sh'), '--automatic'],
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'WorkingDirectory': str(APP),
        'StartCalendarInterval': {'Hour': h, 'Minute': m},
        'StandardOutPath': str(LOG),
        'StandardErrorPath': str(LOG),
        'RunAtLoad': False,
    }
    FILE.write_bytes(plistlib.dumps(data))
    FILE.chmod(0o600)
    result = launchctl('bootstrap', target, str(FILE))
    if result.returncode:
        print(result.stderr)
        raise SystemExit('LaunchAgent kon niet worden geactiveerd.')
    print(f'Dagelijkse synchronisatie ingesteld op {hour}.')
    print('Werkt wanneer de Mac aanstaat en je bent ingelogd.')
    print(f'Logbestand: {LOG}')


if __name__ == '__main__':
    main()
