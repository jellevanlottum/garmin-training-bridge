#!/usr/bin/env python3
"""Export private training metrics, NEVER GPS or credentials, from local Garmin FIT/TCX/GPX.

The output is intentionally allowlisted. No activity titles, places, coordinates,
start times, or personal details are exported. Source filenames are NOT uploaded.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

VERSION = 1
DATA_HOME = Path(os.environ.get('GARMIN_TRAINING_DIR', str(Path.home() / 'GarminTraining'))).expanduser()
CACHE = DATA_HOME / '.github_export_cache'
ACTIVITY_COLUMNS = ['date', 'activity_id', 'sport', 'source', 'distance_km', 'moving_min', 'pace_sec_km', 'avg_hr_bpm', 'max_hr_bpm', 'avg_cadence_spm', 'record_count']
KM_COLUMNS = ['date', 'activity_id', 'km', 'split_seconds', 'split_pace_sec_km', 'avg_hr_bpm', 'avg_cadence_spm']
STREAM_COLUMNS = ['date', 'activity_id', 'elapsed_seconds', 'distance_km', 'heart_rate_bpm', 'cadence_spm', 'pace_sec_km_last_interval']


def number(value, default=None):
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default


def integer(value):
    n = number(value)
    return round(n) if n is not None else ''


def rnd(value, places=2):
    n = number(value)
    return round(n, places) if n is not None else ''


def dt(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def localtag(tag):
    return tag.rsplit('}', 1)[-1]


def xml_child_text(node, *path):
    current = node
    for tag in path:
        current = next((x for x in current if localtag(x.tag) == tag), None) if current is not None else None
        if current is None:
            return None
    return current.text


def parse_tcx(path):
    root = ET.parse(path).getroot()
    sports = [el.get('Sport', '').lower() for el in root.iter() if localtag(el.tag) == 'Activity']
    sport = 'running' if 'running' in sports else (sports[0] if sports else 'unknown')
    recs = []
    lap_meters = 0.0
    lap_seconds = 0.0
    for el in root.iter():
        t = localtag(el.tag)
        if t == 'Lap':
            lap_meters += number(xml_child_text(el, 'DistanceMeters'), 0) or 0
            lap_seconds += number(xml_child_text(el, 'TotalTimeSeconds'), 0) or 0
        elif t == 'Trackpoint':
            stamp = dt(xml_child_text(el, 'Time'))
            distance = number(xml_child_text(el, 'DistanceMeters'))
            hr = number(xml_child_text(el, 'HeartRateBpm', 'Value'))
            # TCX extensions may include RunCadence at either depth.
            cadence = number(xml_child_text(el, 'Cadence'))
            if cadence is None:
                ext = next((x for x in el.iter() if localtag(x.tag) == 'RunCadence'), None)
                cadence = number(ext.text) if ext is not None else None
            recs.append([stamp, distance, hr, cadence])
    return {'sport': sport, 'distance_m': lap_meters or None, 'duration_s': lap_seconds or None, 'records': recs}


def parse_gpx(path):
    root = ET.parse(path).getroot()
    recs = []
    for el in root.iter():
        if localtag(el.tag) != 'trkpt':
            continue
        stamp = dt(xml_child_text(el, 'time'))
        hr = cadence = None
        for child in el.iter():
            k = localtag(child.tag).lower()
            if k in ('hr', 'heartrate'):
                hr = number(child.text)
            elif k in ('cad', 'cadence', 'runcadence'):
                cadence = number(child.text)
        # GPX coordinates are intentionally NEVER copied into results.
        recs.append([stamp, None, hr, cadence])
    return {'sport': 'unknown', 'distance_m': None, 'duration_s': None, 'records': recs}


def parse_fit(path):
    from fitparse import FitFile
    fit = FitFile(str(path), data_processor=None)
    session = {}
    recs = []
    for msg in fit.get_messages():
        if msg.name == 'session':
            for key in ('sport', 'total_distance', 'total_timer_time', 'total_elapsed_time', 'avg_heart_rate', 'max_heart_rate', 'avg_running_cadence', 'avg_cadence'):
                val = msg.get_value(key)
                if val is not None:
                    session[key] = val
        elif msg.name == 'record':
            # Only extract explicitly allowed, non-location fields.
            recs.append([
                dt(msg.get_value('timestamp')),
                number(msg.get_value('distance')),
                number(msg.get_value('heart_rate')),
                number(msg.get_value('cadence')),
            ])
    return {
        'sport': str(session.get('sport') or 'unknown').lower(),
        'distance_m': number(session.get('total_distance')),
        'duration_s': number(session.get('total_timer_time') or session.get('total_elapsed_time')),
        'avg_hr': number(session.get('avg_heart_rate')),
        'max_hr': number(session.get('max_heart_rate')),
        'avg_cadence': number(session.get('avg_running_cadence') or session.get('avg_cadence')),
        'records': recs,
    }


def normalize_cadence(c):
    c = number(c)
    if c is None or c <= 0 or c > 300:
        return None
    # Older FIT/TCX devices may record per-leg cadence. Mark as approximation.
    return c * 2 if c < 110 else c


def enrich(source, path, overview):
    m = re.fullmatch(r'(\d{4}-\d{2}-\d{2})_(\d+)\.(fit|tcx|gpx)', path.name, re.I)
    if not m:
        return None
    day, ident, extension = m.groups()
    if extension.lower() == 'fit':
        data = parse_fit(path)
    elif extension.lower() == 'tcx':
        data = parse_tcx(path)
    else:
        data = parse_gpx(path)
    old = overview.get(ident, {})
    sport = data['sport']
    garmin_sport = str(old.get('type') or '').lower()
    if sport == 'unknown' and garmin_sport:
        sport = garmin_sport
    # Export running only. Unknown activities are also omitted, not guessed.
    if not ('running' in sport or sport in ('run', 'treadmill_running', 'trail_running')):
        return None
    dist = data.get('distance_m')
    if not dist and number(old.get('afstand_km')) is not None:
        dist = number(old.get('afstand_km')) * 1000
    duration = data.get('duration_s')
    if not duration and old.get('duur'):
        try:
            parts = [float(v) for v in old['duur'].split(':')]
            duration = sum(v * (60 ** i) for i, v in enumerate(reversed(parts)))
        except ValueError:
            pass
    recs = data['records']
    if dist is None:
        seen = [r[1] for r in recs if r[1] is not None]
        dist = max(seen) if seen else None
    if duration is None:
        ts = [r[0] for r in recs if r[0] is not None]
        duration = (ts[-1] - ts[0]).total_seconds() if len(ts) >= 2 else None
    hr = data.get('avg_hr') or number(old.get('hartslag_gem'))
    if not hr:
        hrs = [r[2] for r in recs if r[2] and 35 < r[2] < 230]
        hr = sum(hrs) / len(hrs) if hrs else None
    maxhr = data.get('max_hr') or number(old.get('hartslag_max'))
    if not maxhr:
        maxhr = max((r[2] for r in recs if r[2] and 35 < r[2] < 230), default=None)
    avg_cad = data.get('avg_cadence')
    if not avg_cad:
        cads = [normalize_cadence(r[3]) for r in recs]
        cads = [c for c in cads if c]
        avg_cad = sum(cads)/len(cads) if cads else None
    else:
        avg_cad = normalize_cadence(avg_cad)
    # For any laps and stream, only relative elapsed time, never exact clock time.
    cleaned = []
    first_t = next((r[0] for r in recs if r[0] is not None), None)
    for stamp, metres, heart, cadence in recs:
        if first_t is None or stamp is None:
            continue
        sec = (stamp - first_t).total_seconds()
        if sec < 0 or sec > 86400:
            continue
        cleaned.append([sec, metres, heart, normalize_cadence(cadence)])
    cleaned.sort(key=lambda row: row[0])
    kilometres = split_kilometres(cleaned, day, ident)
    stream = sample_stream(cleaned, day, ident)
    pace = duration * 1000 / dist if duration and dist and dist > 100 else None
    return {
        'activity': dict(zip(ACTIVITY_COLUMNS, [day, ident, sport, extension.lower(), rnd(dist/1000, 3) if dist else '', rnd(duration/60, 2) if duration else '', rnd(pace, 1), integer(hr), integer(maxhr), integer(avg_cad), len(recs)])),
        'km': kilometres, 'stream': stream,
    }


def split_kilometres(records, day, ident):
    # Strictly require monotone cumulative distance. Missing data => no invented splits.
    clean = []
    for sec, metres, hr, cad in records:
        if metres is None or metres < 0:
            continue
        if clean and (metres < clean[-1][1] - 5 or sec <= clean[-1][0]):
            continue
        if clean and metres - clean[-1][1] > 1200:
            continue
        clean.append([sec, metres, hr, cad])
    if len(clean) < 2:
        return []
    out, threshold, prev_at = [], 1000.0, 0.0
    seg_hr, seg_cad = [], []
    for i in range(1, len(clean)):
        a, b = clean[i-1], clean[i]
        if b[2] and 35 < b[2] < 230:
            seg_hr.append(b[2])
        if b[3] and 100 < b[3] < 240:
            seg_cad.append(b[3])
        while a[1] < threshold <= b[1] and threshold <= 100000:
            frac = (threshold - a[1]) / (b[1] - a[1]) if b[1] > a[1] else 0
            at = a[0] + frac * (b[0] - a[0])
            lap_seconds = at - prev_at
            if 140 < lap_seconds < 1800:
                out.append(dict(zip(KM_COLUMNS, [day, ident, round(threshold/1000), rnd(lap_seconds, 1), rnd(lap_seconds, 1), integer(sum(seg_hr)/len(seg_hr)) if seg_hr else '', integer(sum(seg_cad)/len(seg_cad)) if seg_cad else ''])))
            prev_at, threshold = at, threshold+1000
            seg_hr, seg_cad = [], []
    return out


def sample_stream(records, day, ident, seconds=30):
    out = []
    prev = None
    last_bucket = -1
    for sec, dist, hr, cad in records:
        bucket = int(sec // seconds)
        if bucket == last_bucket:
            continue
        last_bucket = bucket
        pace = None
        if prev and dist is not None and prev[1] is not None:
            delta_d, delta_t = dist-prev[1], sec-prev[0]
            if delta_d > 0 and delta_t > 0 and delta_d / delta_t < 12:
                pace = delta_t*1000/delta_d
                if not 130 <= pace <= 2400:
                    pace = None
        out.append(dict(zip(STREAM_COLUMNS, [day, ident, integer(sec), rnd(dist/1000, 3) if dist is not None else '', integer(hr), integer(cad), rnd(pace, 1)])))
        prev = [sec, dist]
    return out


def read_overview(path):
    if not path.exists():
        return {}
    with path.open(encoding='utf-8-sig', newline='') as f:
        return {row['garmin_id']: row for row in csv.DictReader(f) if row.get('garmin_id')}


def write_csv(path, columns, rows):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def run(activity_dir, out_dir, recent_count=20):
    if not activity_dir.is_dir():
        raise RuntimeError('Geen activiteitenmap gevonden. Synchroniseer Garmin eerst.')
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CACHE, 0o700)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = read_overview(activity_dir.parent / 'overzicht.csv')
    files = sorted([p for p in activity_dir.iterdir() if p.suffix.lower() in ('.fit', '.tcx', '.gpx') and p.is_file()])
    result, failed, cached = [], 0, 0
    for path in files:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d+\.(fit|tcx|gpx)', path.name, re.I):
            continue
        cache_path = CACHE / (path.name + '.json')
        stamp = {'version': VERSION, 'size': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns}
        try:
            try:
                blob = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
            except (json.JSONDecodeError, UnicodeError, OSError):
                blob = {}
            if blob.get('signature') == stamp:
                record = blob.get('result')
                cached += 1
            else:
                record = enrich(None, path, index)
                cache_path.write_text(json.dumps({'signature': stamp, 'result': record}, ensure_ascii=False), encoding='utf-8')
                cache_path.chmod(0o600)
            if record:
                result.append(record)
        except Exception as exc:
            failed += 1
            print(f'Kan {path.name} niet lezen: {type(exc).__name__}: {exc}', file=sys.stderr)
    result.sort(key=lambda r: (r['activity']['date'], r['activity']['activity_id']), reverse=True)
    activities = [r['activity'] for r in result]
    kms = [k for r in result for k in r['km']]
    streams = [x for r in result[:recent_count] for x in r['stream']]
    write_csv(out_dir / 'activities.csv', ACTIVITY_COLUMNS, activities)
    write_csv(out_dir / 'kilometres.csv', KM_COLUMNS, kms)
    write_csv(out_dir / 'recent_stream.csv', STREAM_COLUMNS, streams)
    # Stable JSON: don't include timestamp, host, file path or username.
    (out_dir / 'about.json').write_text(json.dumps({
        'schema': 'GarminTrainingPrivateMetrics-v1',
        'activity_count': len(activities),
        'oldest_date': activities[-1]['date'] if activities else None,
        'newest_date': activities[0]['date'] if activities else None,
        'recent_stream_count': min(recent_count, len(activities)),
        'privacy': 'No GPS coordinates, route names, source filenames, passwords or exact start timestamps. Activity dates and Garmin activity IDs ARE included.',
        'note': 'Paces are calculated from distance and duration; kilometer splits are inferred from recorded cumulative distance and elapsed time. Cadence may be doubled from per-leg units.'
    }, indent=2) + '\n', encoding='utf-8')
    print(f'Gereed: {len(activities)} looptrainingen, {len(kms)} km-splits, {len(streams)} meetpunten van de nieuwste {recent_count} trainingen.')
    print(f'Lokaal opgeslagen export: {out_dir}')
    if failed:
        print(f'Waarschuwing: {failed} bestanden konden niet worden gelezen; bestaande Garmin-bestanden zijn niet gewijzigd.')
    return len(activities)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, default=DATA_HOME / 'activiteiten')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--recent', type=int, default=20)
    a = p.parse_args()
    if not 1 <= a.recent <= 100:
        p.error('--recent moet tussen 1 en 100 liggen')
    return 0 if run(a.source, a.out, a.recent) > 0 else 2


if __name__ == '__main__':
    sys.exit(main())
