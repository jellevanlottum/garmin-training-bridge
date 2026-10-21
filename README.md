# Garmin Training Bridge (macOS)

**Garmin Connect → Mac → a PRIVATE GitHub data repository → ChatGPT**

A small, reusable, unofficial, open-source pipeline for running training analysis.
This **public code repository** contains *no athlete data, credentials or GPS routes*.
Each user creates their **own separate, private repository** for their filtered training metrics.

## Prerequisites

- macOS and Python 3.12 or newer: <https://www.python.org/downloads/macos/>
- Git: preinstalled with Xcode Command Line Tools, if needed run `xcode-select --install`
- GitHub CLI: <https://cli.github.com/> (with Homebrew: `brew install gh`)
- A Garmin Connect account
- A GitHub account and a **new, EMPTY, PRIVATE** repository for the data, for example `runner123/garmin-training-data`

## Fast setup

1. Download the code ZIP (or clone this public template). Unzip it.
2. **Read the scripts** before running them. These are unsigned macOS scripts, so Gatekeeper may block them. Only approve a file you trust; never disable Gatekeeper globally.
3. Double-click `01_INSTALL.command`. Enter **your own** `OWNER/PRIVATE_REPO` and optionally a local data folder. The settings are stored in `~/Library/Application Support/GarminTrainingBridge/config.json`, not in this public code repository.
4. Double-click `02_FIRST_SYNC.command`. Garmin will ask for your credentials locally (with MFA as needed); GitHub CLI opens a browser sign-in if necessary. **Never send tokens or passwords to anyone.**
5. Verify the destination is still **Private**, and review its `data/` files before granting third-party access.
6. Double-click `03_ENABLE_DAILY.command` to set a daily time. The Mac must be on and logged in when it runs.
7. Optional: `05_DOWNLOAD_HISTORY.command` works through older FIT/TCX/GPX activities in resumable batches. After downloading old records, run `02_FIRST_SYNC.command` to publish newly imported summaries.

To change the target repo or folder, double-click `06_CHANGE_SETTINGS.command`.
To stop scheduling, double-click `04_DISABLE_DAILY.command`.

## What is uploaded?

Only an explicit whitelist of generated files, and only if `gh repo view` confirms the destination repository is `PRIVATE`:

| File | Content |
| --- | --- |
| `data/activities.csv` | Dates, activity IDs, distance, duration, pace, average/max HR, cadence |
| `data/kilometres.csv` | Inferred kilometer splits, HR and cadence |
| `data/recent_stream.csv` | Relative elapsed time and approximate 30-second samples of the most recent runs |
| `data/about.json` | Coverage and data schema |

**Not uploaded:** Garmin login details, OAuth tokens, FIT/TCX/GPX files, GPS coordinates, route names, workout titles, exact start times, or other documents on the Mac. Activity **dates**, Garmin **activity IDs**, heart rate and pace remain personal data, so keep the destination PRIVATE. GitHub stores revision history, including older exports.

## How it works

- The unofficial [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) package fetches a user's activities into a local folder. Token files remain in `~/.garminconnect`.
- FIT, TCX and GPX input files are parsed locally. Non-GPS fields are allowlisted for export.
- GitHub CLI pushes **only** the four data outputs and a generated README/.gitignore to the chosen private repository.
- `launchd` can run the pipeline each day when the Mac is awake and user is logged in.
- To read the uploaded data in ChatGPT, users separately connect their GitHub account and grant access to their selected private data repository. A GitHub CLI login alone does *not* grant ChatGPT access.

## Limitations / security

- This is an **unofficial** Garmin connection, not the official Garmin Connect Developer API. Garmin changes or rate limits can break syncing.
- The historical import may not recover every activity; old formats can lack heart rate or distance.
- Derived kilometre splits and cadence normalization are approximations; do not interpret them as medical diagnostics.
- Both the GitHub CLI token and Garmin session are stored locally. Protect your Mac and don't back these tokens up into the public code repo.
- The GitHub app/connector may offer broad permissions: select only the private data repo when possible.
- **Never make the private data repository public**. If you accidentally publish sensitive files, removing them in a later commit does not erase Git history.
- Use only for data you have permission to access. This is offered as-is, with no promise of uninterrupted service.

## Sharing the code

Create a **new public GitHub repository just for these source files**. Never turn a personal data repository public, and do not fork one. GitHub: Repository → Settings → General → **Template repository**.
Other users can select **Use this template** and create their own code repository (or download the code ZIP). They should always separately create a private data repository.

## File map

- `garmin_sync.py` — recent activity download
- `garmin_history.py` — optional historical downloader in batches
- `export_training.py` — privacy-filtered metrics export
- `pipeline.py` — verified private GitHub sync and push
- `configuration.py` — user-specific settings outside source control
- `scheduler.py` — macOS daily LaunchAgent
- `01_*` through `06_*` — double-clickable scripts

## Licence

MIT. Contributions and issue reports welcome; please never attach personal Garmin data or tokens to issues.
