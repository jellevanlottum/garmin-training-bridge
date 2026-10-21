#!/usr/bin/env python3
"""Garmin Connect archive extension (v4) for existing GarminLokaleSync installation.

Downloads original FIT/TCX/GPX files; falls back to Garmin-generated TCX/GPX
when original not available. Existing activity files are not overwritten.
Uses third-party unofficial garminconnect and the local session from v2.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
import zipfile
from typing import Any

import garmin_sync as base

DATA_HOME = base.DATA_HOME
STATE_DIR = DATA_HOME / "voortgang"
ACTIVITY_DIR = base.ACTIVITIES
PAGE_SIZE = 40
MAX_UNCOMPRESSED = 100 * 1024 * 1024
SUPPORTED = ("fit", "tcx", "gpx")


def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
    path.chmod(0o600)


def initial_state(scope: str) -> dict:
    # Deliberately NOT reusing v3's state. v3 skipped legacy TCX/GPX files,
    # so we need a one-time re-scan of its visited activities.
    return {"version": 4, "scope": scope, "offset": 0, "done": False,
            "checked": 0, "downloaded": 0, "already_present": 0,
            "missing": {}, "started_utc": datetime.now(timezone.utc).isoformat()}


def read_state(path: Path, scope: str) -> dict:
    if not path.exists():
        return initial_state(scope)
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not (isinstance(state, dict) and state.get("version") == 4
            and state.get("scope") == scope
            and type(state.get("offset")) is int and state["offset"] >= 0):
        raise ValueError(f"Ongeldig voortgangsbestand {path}")
    return state


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


def existing_file(date: str, activity_id: str) -> Path | None:
    for ext in SUPPORTED:
        path = ACTIVITY_DIR / f"{date}_{activity_id}.{ext}"
        if path.is_file() and path.stat().st_size >= 12:
            return path
    return None


def store_file(path: Path, payload: bytes) -> None:
    # Never overwrite an existing file. Staged write prevents partial files.
    if path.exists():
        return
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
        tmp.replace(path)
        path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


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


def store_activity(client: Any, activity: dict, index: dict) -> tuple[str, str]:
    activity_id, row = base.describe_activity(activity)
    date = row["datum"]
    previous = existing_file(date, activity_id)
    if previous:
        # Column called fit_bestand by old v2 schema; filename may be TCX/GPX.
        row["fit_bestand"] = f"activiteiten/{previous.name}"
        index[activity_id] = row
        return "existing", previous.suffix.lower().lstrip(".")
    result = get_activity_payload(client, activity_id)
    if result is None:
        return "missing", ""
    ext, payload = result
    target = ACTIVITY_DIR / f"{date}_{activity_id}.{ext}"
    store_file(target, payload)
    row["fit_bestand"] = f"activiteiten/{target.name}"
    index[activity_id] = row
    return "new", ext


def scan(client: Any, scope: str, max_new: int, max_scanned: int,
         delay: float = 2.0, page_delay: float = 3.0):
    DATA_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    ACTIVITY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_file = STATE_DIR / f"{scope}_v4.json"
    state = read_state(state_file, scope)
    if state["done"]:
        print(f"Alle activiteiten in deze reeks zijn gecontroleerd ({state['checked']}).")
        return state
    index = base.load_index()
    processed = new = existing = unavailable = 0
    print(f"Versie 4: gestart vanaf positie {state['offset']} (oude v3-voortgang blijft bewaard).", flush=True)
    print("Bestaande FIT/TCX/GPX-bestanden worden niet opnieuw gedownload.", flush=True)
    while new < max_new and processed < max_scanned:
        start = state["offset"]
        opts = {"start": start, "limit": PAGE_SIZE}
        if scope == "running":
            opts["activitytype"] = "running"
        try:
            page = request(lambda: client.get_activities(**opts))
        except Exception as exc:
            save_json(state_file, state)
            print(f"Activiteitenlijst niet beschikbaar: {type(exc).__name__}: {exc}", flush=True)
            if auth_or_limit(exc):
                print("Garmin beperkt mogelijk verzoeken. Probeer later opnieuw.", flush=True)
            raise
        if isinstance(page, dict):
            page = page.get("activityList", [])
        if not isinstance(page, list):
            raise TypeError("Garmin gaf onverwacht antwoord op activiteitenlijst")
        if not page:
            state["done"] = True
            save_json(state_file, state)
            break
        print(f"  Pagina {start}: {len(page)} activiteiten", flush=True)
        for activity in page:
            if processed >= max_scanned or new >= max_new:
                break
            activity_id = str(activity.get("activityId", "?")) if isinstance(activity, dict) else "?"
            try:
                outcome, ext = store_activity(client, activity, index)
            except Exception as exc:
                base.save_index(index)
                save_json(state_file, state)
                print(f"Gestopt bij {activity_id}; positie blijft bewaard: {type(exc).__name__}: {exc}", flush=True)
                raise
            if outcome == "new":
                new += 1
                state["downloaded"] += 1
                print(f"  Opgeslagen: {activity.get('startTimeLocal','')[:10]} / {activity_id}.{ext}", flush=True)
            elif outcome == "existing":
                existing += 1
                state["already_present"] += 1
            else:
                unavailable += 1
                state["missing"][activity_id] = activity.get("startTimeLocal", "")[:10]
                print(f"  Geen bronbestand (FIT/TCX/GPX) voor {activity_id}", flush=True)
            processed += 1
            state["checked"] += 1
            state["offset"] += 1
            state["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
            base.save_index(index)
            save_json(state_file, state)
            if outcome != "existing":
                time.sleep(delay)
        if new < max_new and processed < max_scanned:
            time.sleep(page_delay)
    print("\n--- Batchresultaat ---")
    print(f"Nieuwe bestanden: {new}; reeds aanwezig: {existing}; zonder gegevens: {unavailable}")
    print(f"Totaal gecontroleerd door v4: {state['checked']}; volgende positie: {state['offset']}")
    print(f"Einde Garmin-geschiedenis: {'ja' if state['done'] else 'nog niet'}")
    print(f"Bestanden: {ACTIVITY_DIR}")
    print(f"Overzicht: {base.CSV_FILE}")
    print(f"Voortgang: {state_file}")
    if not state["done"]:
        print("Start dit bestand opnieuw om verder te gaan.")
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description="Volledige Garmin-geschiedenis, inclusief oude TCX/GPX")
    parser.add_argument("--scope", choices=("running", "all"), default="running")
    parser.add_argument("--max-new", type=int, default=125)
    parser.add_argument("--max-scanned", type=int, default=500)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args(argv)
    if not (1 <= args.max_new <= 500 and 1 <= args.max_scanned <= 3000 and 0.5 <= args.delay <= 60):
        parser.error("Ongeldige batchinstellingen")
    try:
        from garminconnect import (Garmin, GarminConnectAuthenticationError,
                                   GarminConnectConnectionError, GarminConnectTooManyRequestsError)
        client = base.login(Garmin, GarminConnectAuthenticationError,
                            GarminConnectConnectionError, GarminConnectTooManyRequestsError)
        scan(client, args.scope, args.max_new, args.max_scanned, args.delay)
        return 0
    except KeyboardInterrupt:
        print("Handmatig gestopt. Voortgang is opgeslagen.")
        return 130
    except Exception as exc:
        print(f"Niet afgerond: {type(exc).__name__}: {exc}")
        print("De volgende uitvoering hervat bij dezelfde activiteit.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
