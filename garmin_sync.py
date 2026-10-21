#!/usr/bin/env python3
"""Read-only Garmin Connect activity archiver for personal use.

Uses the unofficial python-garminconnect client. Stores original activity FITs
and summary CSV locally. Never uploads, modifies or deletes Garmin data.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from getpass import getpass
import io
import json
import logging
from pathlib import Path
from typing import Any
import sys
import time
import zipfile

DATA_HOME = Path(__import__("os").environ.get("GARMIN_TRAINING_DIR", str(Path.home() / "GarminTraining"))).expanduser()
ACTIVITIES = DATA_HOME / "activiteiten"
CSV_FILE = DATA_HOME / "overzicht.csv"
TOKENSTORE = Path.home() / ".garminconnect"
MAX_UNCOMPRESSED = 100 * 1024 * 1024
SUPPORTED = ("fit", "tcx", "gpx")
FIELDS = [
    "datum", "garmin_id", "naam", "afstand_km", "duur", "tempo_min_km",
    "hartslag_gem", "hartslag_max", "cadans_gem", "type", "fit_bestand",
]


def fmt_duration(seconds):
    if seconds is None:
        return ""
    total = round(float(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def fmt_pace(meters, seconds):
    if not meters or not seconds:
        return ""
    sec_per_km = round(float(seconds) * 1000 / float(meters))
    mins, secs = divmod(sec_per_km, 60)
    return f"{mins}:{secs:02d}"


def clean_number(value, places=1):
    return round(float(value), places) if value is not None else ""


def describe_activity(activity):
    raw_id = activity.get("activityId")
    if raw_id is None or not str(raw_id).isdigit():
        raise ValueError("Activiteit zonder geldige Garmin-ID")
    activity_id = str(raw_id)
    date_str = str(activity.get("startTimeLocal") or activity.get("startTimeGMT") or "")
    date_part = date_str[:10]
    try:
        datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        date_part = "onbekend"
    activity_type = activity.get("activityType") or {}
    type_key = activity_type.get("typeKey", "") if isinstance(activity_type, dict) else str(activity_type)
    meters = activity.get("distance")
    seconds = activity.get("duration")
    row = {
        "datum": date_part,
        "garmin_id": activity_id,
        "naam": str(activity.get("activityName") or "Hardlopen"),
        "afstand_km": clean_number(float(meters) / 1000, 3) if meters is not None else "",
        "duur": fmt_duration(seconds),
        "tempo_min_km": fmt_pace(meters, seconds),
        "hartslag_gem": clean_number(activity.get("averageHR"), 0),
        "hartslag_max": clean_number(activity.get("maxHR"), 0),
        "cadans_gem": clean_number(activity.get("averageRunningCadenceInStepsPerMinute"), 0),
        "type": type_key,
        "fit_bestand": f"activiteiten/{date_part}_{activity_id}.fit",
    }
    return activity_id, row


def auth_or_limit(exc: Exception) -> bool:
    typ = type(exc).__name__.lower()
    msg = str(exc).lower()
    return ("auth" in typ or "toomanyrequests" in typ or
            any(s in msg for s in ("429", "401", "403", "rate limit")))


def is_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("404", "not found", "500", "nullpointerexception"))


def request(fn, *, tries: int = 3) -> Any:
    for num in range(tries):
        try:
            return fn()
        except Exception as exc:
            if num == tries - 1 or auth_or_limit(exc) or is_unavailable(exc):
                raise
            delay = 5 * (num + 1)
            print(f"  Tijdelijke fout: {type(exc).__name__}; opnieuw over {delay}s", flush=True)
            time.sleep(delay)


def valid_file(ext: str, data: bytes) -> bool:
    if not data or len(data) > MAX_UNCOMPRESSED:
        return False
    if ext == "fit":
        return len(data) >= 12 and data[8:12] == b".FIT"
    # No XML parser needed; safeguard against HTML errors and empty response.
    # Permit XML prolog/comments preceding root.
    prefix = data[:4096].lstrip(b"\xef\xbb\xbf\r\n\t ").lower()
    if ext == "tcx":
        return b"<trainingcenterdatabase" in prefix
    if ext == "gpx":
        return b"<gpx" in prefix
    return False


def extract_original(blob: bytes) -> tuple[str, bytes] | None:
    data = bytes(blob)
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for ext in SUPPORTED:
                for entry in z.infolist():
                    if (entry.is_dir() or entry.file_size > MAX_UNCOMPRESSED or
                            not entry.filename.lower().endswith("." + ext)):
                        continue
                    extracted = z.read(entry)
                    if valid_file(ext, extracted):
                        return ext, extracted
        return None
    for ext in SUPPORTED:
        if valid_file(ext, data):
            return ext, data
    return None


def get_activity_payload(client: Any, activity_id: str) -> tuple[str, bytes] | None:
    # Prefer raw, original source, including legacy TCX or GPX.
    try:
        original = request(lambda: client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL))
        parsed = extract_original(original)
        if parsed:
            return parsed
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"  Origineel niet leesbaar voor {activity_id}: {type(exc).__name__}", flush=True)
    except Exception as exc:
        if not is_unavailable(exc):
            raise
    # Legacy/manual activities may have no original; Garmin can sometimes
    # generate TCX or GPX with the available per-point samples instead.
    for ext, kind in (("tcx", "TCX"), ("gpx", "GPX")):
        try:
            blob = request(lambda: client.download_activity(
                activity_id, dl_fmt=getattr(client.ActivityDownloadFormat, kind)))
            if valid_file(ext, bytes(blob)):
                return ext, bytes(blob)
        except Exception as exc:
            if auth_or_limit(exc):
                raise
            if not is_unavailable(exc):
                print(f"  {kind} niet beschikbaar ({type(exc).__name__})", flush=True)
    return None


def existing_file(date, activity_id):
    for ext in ("fit", "tcx", "gpx"):
        path = ACTIVITIES / f"{date}_{activity_id}.{ext}"
        if path.is_file() and path.stat().st_size >= 12:
            return path
    return None

def load_index():
    if not CSV_FILE.exists():
        return {}
    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["garmin_id"]: row for row in csv.DictReader(handle) if row.get("garmin_id")}


def save_index(index):
    temp_path = CSV_FILE.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(index.values(), key=lambda x: (x["datum"], x["garmin_id"]), reverse=True))
    temp_path.replace(CSV_FILE)
    CSV_FILE.chmod(0o600)


def login(Garmin, auth_error, connection_error, rate_error, noninteractive=False):
    if (TOKENSTORE / "garmin_tokens.json").exists():
        try:
            client = Garmin()
            client.login(str(TOKENSTORE))
            print("Ingelogd met lokaal bewaarde sessie.")
            return client
        except (auth_error, connection_error):
            if noninteractive:
                raise RuntimeError("Bewaarde sessie is verlopen. Start 02_SYNCHRONISEREN.command handmatig.")
        except rate_error:
            raise

    if noninteractive:
        raise RuntimeError("Geen Garmin-sessie gevonden. Start 02_SYNCHRONISEREN.command handmatig.")
    print("Eerste keer: log lokaal in bij Garmin Connect.")
    email = input("Garmin e-mailadres: ").strip()
    if not email:
        raise ValueError("Een e-mailadres is nodig")
    password = getpass("Garmin wachtwoord (niet zichtbaar): ")
    if not password:
        raise ValueError("Een wachtwoord is nodig")
    client = Garmin(email=email, password=password, prompt_mfa=lambda: input("Garmin verificatiecode: ").strip())
    password = None
    client.login(str(TOKENSTORE))
    print(f"Garmin-sessie opgeslagen buiten deze map: {TOKENSTORE}")
    return client


def fetch_activities(client, desired_count):
    """Page through newest runs, without needlessly polling whole account."""
    collected = []
    page_size = 50
    offset = 0
    while len(collected) < desired_count:
        limit = min(page_size, desired_count - len(collected))
        page = client.get_activities(start=offset, limit=limit, activitytype="running")
        if isinstance(page, dict):
            page = page.get("activityList", [])
        if not isinstance(page, list):
            raise RuntimeError("Garmin gaf een onverwachte activiteitenlijst terug")
        if not page:
            break
        collected.extend(page)
        offset += len(page)
        if len(page) < limit:
            break
        if len(collected) < desired_count:
            time.sleep(1)
    return collected[:desired_count]


def run(client, count, sleep_seconds=1.25):
    DATA_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    ACTIVITIES.mkdir(parents=True, exist_ok=True, mode=0o700)
    index = load_index()
    activities = fetch_activities(client, count)
    print(f"{len(activities)} recente hardloopactiviteiten gevonden.")
    added = 0
    skipped = 0
    errors = 0
    for activity in activities:
        try:
            activity_id, row = describe_activity(activity)
            existing = existing_file(row["datum"], activity_id)
            if existing:
                row["fit_bestand"] = f"activiteiten/{existing.name}"
                skipped += 1
                index[activity_id] = row
                continue
            result = get_activity_payload(client, activity_id)
            if result is None:
                errors += 1
                print(f"  No FIT/TCX/GPX source for {activity_id}")
                continue
            ext, payload = result
            path = ACTIVITIES / f'{row["datum"]}_{activity_id}.{ext}'
            tmp = path.with_name(path.name + ".tmp")
            try:
                with tmp.open("xb") as handle:
                    handle.write(payload)
                tmp.replace(path)
                path.chmod(0o600)
            finally:
                tmp.unlink(missing_ok=True)
            row["fit_bestand"] = f"activiteiten/{path.name}"
            index[activity_id] = row
            added += 1
            print(f"  New: {row['datum']} | {row['afstand_km']} km ({ext.upper()})")
            time.sleep(sleep_seconds)
        except Exception as exc:
            errors += 1
            print(f"  Skipped: {activity.get('activityId', '?')} ({type(exc).__name__}: {exc})")
            save_index(index)
            if auth_or_limit(exc):
                raise RuntimeError("Garmin authentication/rate limit issue. Try again later.") from exc
    save_index(index)
    print(f"Klaar: {added} nieuwe FIT-bestanden, {skipped} al aanwezig, {errors} overgeslagen.")
    print(f"FIT-map: {ACTIVITIES}")
    print(f"Overzicht: {CSV_FILE}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synchroniseer lokale Garmin hardloop-FIT-bestanden")
    parser.add_argument("--count", type=int, default=30, help="Aantal meest recente runs om te controleren (standaard: 30)")
    parser.add_argument("--noninteractive", action="store_true", help="Voor automatische synchronisatie zonder wachtwoordprompt")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 5000:
        parser.error("--count moet tussen 1 en 5000 zijn")
    try:
        from garminconnect import (
            Garmin, GarminConnectAuthenticationError,
            GarminConnectConnectionError, GarminConnectTooManyRequestsError,
        )
    except ImportError:
        print("Bibliotheek ontbreekt. Start eerst 01_INSTALLEREN.command.")
        return 1
    logging.getLogger("garminconnect").setLevel(logging.ERROR)
    try:
        client = login(
            Garmin, GarminConnectAuthenticationError,
            GarminConnectConnectionError, GarminConnectTooManyRequestsError,
            noninteractive=args.noninteractive,
        )
        run(client, args.count)
        return 0
    except KeyboardInterrupt:
        print("Afgebroken.")
        return 130
    except Exception as exc:
        print(f"Synchronisatie niet gelukt: {type(exc).__name__}: {exc}")
        print("Controleer Garmin Connect, je internetverbinding en of de onofficiële login nog werkt.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
