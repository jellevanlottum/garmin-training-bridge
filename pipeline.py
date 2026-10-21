#!/usr/bin/env python3
"""Offline local sync + *explicit allowlist* upload to one private GitHub repo."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from configuration import load, APP


def call(args, *, cwd=None, capture=False, check=True):
    res = subprocess.run(args, cwd=cwd, capture_output=capture, text=True)
    if check and res.returncode:
        if capture and res.stderr:
            print(res.stderr.strip(), file=sys.stderr)
        raise RuntimeError(f'Command failed: {args[0]} (exit code {res.returncode})')
    return res.stdout.strip() if capture else res.returncode


def publish(conf, mode):
    repo = conf['data_repository']
    # Refuse public or internal visibility. We do not upload any data until checked.
    if subprocess.run(['gh','auth','status','--hostname','github.com'], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0 and mode == 'manual':
        print('Log in to GitHub CLI using your browser:')
        call(['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'])
    elif subprocess.run(['gh','auth','status','--hostname','github.com'], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0:
        raise RuntimeError('GitHub CLI not authenticated. Run 02_FIRST_SYNC.command.')
    call(['gh', 'auth', 'setup-git'])
    visibility = call(['gh', 'repo', 'view', repo, '--json', 'visibility', '--jq', '.visibility'],capture=True)
    if visibility.upper() != 'PRIVATE':
        raise RuntimeError('STOP: destination GitHub repository is not PRIVATE. Upload blocked.')
    # Ensure data git directory remains separate from public source directory.
    data_home = Path(conf['training_directory'])
    checkout = data_home / 'private-github-repository'
    if not (checkout/'.git').is_dir():
        if checkout.exists():
            raise RuntimeError(f'STOP: folder exists and is not a Git repository: {checkout}')
        checkout.parent.mkdir(parents=True, exist_ok=True)
        call(['gh', 'repo', 'clone', repo, str(checkout)])
    origin = call(['git', 'remote', 'get-url', 'origin'],cwd=checkout,capture=True)
    allowed = {f'https://github.com/{repo}.git',f'https://github.com/{repo}',f'git@github.com:{repo}.git'}
    if origin not in allowed:
        raise RuntimeError(f'STOP: unexpected Git origin: {origin}')
    call(['git','config','user.name','Garmin Training Bridge'],cwd=checkout)
    call(['git','config','user.email','garmin-bridge@users.noreply.github.com'],cwd=checkout)
    heads=subprocess.run(['git','ls-remote','--exit-code','--heads','origin','main'],cwd=checkout,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode
    if heads == 0:
        call(['git', 'pull', '--ff-only', 'origin','main'],cwd=checkout)
    else:
        call(['git', 'checkout', '-B', 'main'],cwd=checkout)

    from export_training import run as export
    count = export(data_home/'activiteiten',checkout/'data',conf['recent_streams'])
    if count == 0:
        raise RuntimeError('No eligible running activities. Nothing was published.')
    readme=checkout/'README.md'
    if not readme.exists():
        readme.write_text('# Garmin training metrics (private)\n\nGenerated running metrics only, no raw FIT/TCX/GPX files or GPS positions.\n',encoding='utf-8')
    ignore=checkout/'.gitignore'
    if not ignore.exists():
        ignore.write_text('*.fit\n*.tcx\n*.gpx\n*.zip\n*.xlsx\n*.csv\n!data/activities.csv\n!data/kilometres.csv\n!data/recent_stream.csv\n*.token\n.env\n',encoding='utf-8')
    # Explicit allowlist: never stage whole directory or secrets.
    paths=['README.md','.gitignore','data/about.json','data/activities.csv','data/kilometres.csv','data/recent_stream.csv']
    call(['git','add','--',*paths],cwd=checkout)
    if call(['git','diff','--cached','--quiet'],cwd=checkout,check=False) == 0:
        print('No changes; private GitHub repository already up to date.')
        return
    call(['git','commit','-m','Update Garmin running metrics'],cwd=checkout)
    call(['git','push','-u','origin','main'],cwd=checkout)
    print(f'Uploaded filtered running metrics to PRIVATE repository: https://github.com/{repo}')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['manual','automatic'],default='manual')
    p.add_argument('--history',action='store_true',help='Historical archive batch, no GitHub upload')
    args=p.parse_args()
    conf=load()
    os.environ['GARMIN_TRAINING_DIR']=conf['training_directory']
    os.umask(0o077)
    if args.history:
        import garmin_history
        sys.exit(garmin_history.main(['--scope','running','--max-new','125','--max-scanned','500']))
    from garmin_sync import main as garmin_main
    print('Checking recent Garmin activities...')
    rc=garmin_main(['--count',str(conf['recent_runs'])]+(['--noninteractive'] if args.mode=='automatic' else []))
    if rc:
        if not (Path(conf['training_directory'])/'activiteiten').is_dir():
            raise RuntimeError('No Garmin training archive available; upload cancelled.')
        print('Garmin retrieval failed; only existing locally downloaded data will be published.')
    publish(conf,args.mode)

if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped.')
        sys.exit(130)
    except Exception as e:
        print(f'Error: {e}',file=sys.stderr)
        sys.exit(1)
