#!/usr/bin/env python3
"""Wearable data import.

Supports:
- Apple Health export (export.xml)
- Garmin Connect activities export (Activities.csv, detected by header)
- Generic CSV (date,metric,value[,unit]) — works for Oura, Whoop, or any device
  if the user formats it, or copy-pasted from a spreadsheet.

Imports map to:
  HKQuantityTypeIdentifierStepCount        → vital metric=steps
  HKQuantityTypeIdentifierRestingHeartRate → vital metric=heart_rate
  HKQuantityTypeIdentifierHeartRate        → vital metric=heart_rate
  HKQuantityTypeIdentifierBodyMass         → weight
  HKCategoryTypeIdentifierSleepAnalysis    → checkin sleep_hours (per night)
  HKQuantityTypeIdentifierVO2Max           → vital metric=vo2_max
  HKQuantityTypeIdentifierBloodPressureSystolic/Diastolic → vital metric=blood_pressure

The aim is "drop and go". User puts export into inbox/, runs import, gets
weeks of data without typing.
"""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        record_vital,
        record_weight,
        load_profile,
        save_profile,
        upsert_record,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        record_vital,
        record_weight,
        load_profile,
        save_profile,
        upsert_record,
        workspace_lock,
    )


APPLE_TYPE_MAP = {
    "HKQuantityTypeIdentifierStepCount":         ("vital", "steps", ""),
    "HKQuantityTypeIdentifierRestingHeartRate":  ("vital", "heart_rate", "bpm"),
    "HKQuantityTypeIdentifierHeartRate":         ("vital", "heart_rate", "bpm"),
    "HKQuantityTypeIdentifierBodyMass":          ("weight", "weight", "kg"),
    "HKQuantityTypeIdentifierVO2Max":            ("vital", "vo2_max", "ml/kg/min"),
    "HKQuantityTypeIdentifierOxygenSaturation":  ("vital", "spo2", "%"),
    "HKQuantityTypeIdentifierBloodPressureSystolic":  ("bp", "systolic", "mmHg"),
    "HKQuantityTypeIdentifierBloodPressureDiastolic": ("bp", "diastolic", "mmHg"),
    "HKCategoryTypeIdentifierSleepAnalysis":     ("sleep", "sleep_hours", "h"),
}


def _parse_apple_date(s: str) -> date | None:
    """Apple stamps are 'YYYY-MM-DD HH:MM:SS ±zzzz'. We just want the date."""
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _import_apple_xml(root: Path, person_id: str, xml_path: Path, max_records: int = 50000) -> dict[str, int]:
    """Stream-parse Apple Health export. Returns counts by metric."""
    counts: dict[str, int] = {}
    daily_buckets: dict[tuple[str, date], list[float]] = {}  # (metric, day) -> values for averaging
    bp_pairs: dict[date, dict[str, float]] = {}
    sleep_per_day: dict[date, float] = {}

    parsed = 0
    for _, elem in ET.iterparse(str(xml_path), events=("end",)):
        if elem.tag != "Record":
            elem.clear()
            continue
        type_attr = elem.get("type", "")
        mapping = APPLE_TYPE_MAP.get(type_attr)
        if not mapping:
            elem.clear()
            continue
        kind, metric, unit = mapping
        start = elem.get("startDate", "")
        end = elem.get("endDate", start)
        value_str = elem.get("value", "")

        d = _parse_apple_date(start)
        if not d:
            elem.clear()
            continue

        try:
            value = float(value_str)
        except (TypeError, ValueError):
            value = 0.0

        if kind == "vital":
            # Aggregate by day: steps→sum, heart_rate→avg
            key = (metric, d)
            daily_buckets.setdefault(key, []).append(value)
        elif kind == "weight":
            # Apple BodyMass usually in kg; sometimes lb. Trust the unit attr.
            unit_attr = (elem.get("unit") or "kg").lower()
            kg = value * 0.453592 if unit_attr.startswith("lb") else value
            record_weight(root, person_id, d.isoformat(), kg, "kg", "Apple Health")
            counts["weight"] = counts.get("weight", 0) + 1
        elif kind == "bp":
            bp_pairs.setdefault(d, {})[metric] = value
        elif kind == "sleep":
            # Sleep records have start/end; sum minutes asleep per day
            try:
                start_dt = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(end[:19], "%Y-%m-%d %H:%M:%S")
                hours = (end_dt - start_dt).total_seconds() / 3600.0
            except ValueError:
                hours = 0.0
            if hours > 0:
                sleep_per_day[d] = sleep_per_day.get(d, 0.0) + hours

        parsed += 1
        elem.clear()
        if parsed >= max_records:
            break

    # Flush daily buckets
    for (metric, d), values in daily_buckets.items():
        if metric == "steps":
            agg = sum(values)
        else:
            agg = sum(values) / len(values)
        unit = "bpm" if metric == "heart_rate" else "ml/kg/min" if metric == "vo2_max" else "%" if metric == "spo2" else ""
        record_vital(root, person_id, d.isoformat(), metric, str(agg), unit, "Apple Health")
        counts[metric] = counts.get(metric, 0) + 1

    # Flush BP pairs
    for d, parts in bp_pairs.items():
        sys = parts.get("systolic")
        dia = parts.get("diastolic")
        if sys and dia:
            record_vital(root, person_id, d.isoformat(), "blood_pressure",
                         f"{int(sys)}/{int(dia)}", "mmHg", "Apple Health")
            counts["blood_pressure"] = counts.get("blood_pressure", 0) + 1

    # Flush sleep into checkins
    if sleep_per_day:
        with workspace_lock(root, person_id):
            profile = load_profile(root, person_id)
            checkins = list(profile.get("daily_checkins", []))
            existing_dates = {str(c.get("date", ""))[:10] for c in checkins}
            for d, hours in sleep_per_day.items():
                if d.isoformat() not in existing_dates:
                    checkins.append({
                        "date": d.isoformat(),
                        "sleep_hours": round(hours, 1),
                        "notes": "imported from Apple Health",
                    })
            profile["daily_checkins"] = sorted(checkins, key=lambda c: str(c.get("date", "")))
            save_profile(root, person_id, profile)
        counts["sleep"] = len(sleep_per_day)

    return counts


# Garmin Connect "Export CSV" (Activities list -> gear icon -> Export CSV) activity
# type labels -> health-skill's workout `type` field. Unrecognized types fall back to
# a lowercase/underscored version of Garmin's own label rather than being dropped.
_GARMIN_TYPE_MAP = {
    "running": "run", "treadmill running": "run", "trail running": "run",
    "track running": "run", "indoor running": "run", "street running": "run",
    "cycling": "cycling", "road cycling": "cycling", "mountain biking": "cycling",
    "indoor cycling": "cycling", "gravel/unpaved cycling": "cycling",
    "walking": "walk", "hiking": "walk", "casual walking": "walk",
    "swimming": "swim", "open water swimming": "swim", "lap swimming": "swim",
    "strength_training": "strength", "strength training": "strength",
}

# Columns this importer trusts. Garmin's CSV export has 30+ locale/device-dependent
# columns (cadence, power, GCT, vertical oscillation, swim SWOLF, dive time, ...);
# ponytail: only the columns present and reliable across nearly every activity type
# are parsed. Add more if a specific metric (e.g. running power) becomes worth the
# per-column fragility of Garmin's export format.
_GARMIN_HEADER_MARKERS = ("activity type", "distance", "time")


def _row_get(row: dict[str, str], *keys: str) -> str:
    """Case-insensitive column lookup — Garmin's export header casing/wording has
    drifted across app versions and locales."""
    lower_map = {(k or "").strip().lower(): v for k, v in row.items()}
    for key in keys:
        v = lower_map.get(key.lower())
        if v not in (None, ""):
            return v
    return ""


def _normalize_garmin_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in _GARMIN_TYPE_MAP:
        return _GARMIN_TYPE_MAP[key]
    return key.replace(" ", "_").replace("/", "_") or "other"


def _parse_garmin_duration_min(raw: str) -> float | None:
    """Garmin 'Time' is 'H:MM:SS' or 'MM:SS'."""
    raw = (raw or "").strip()
    if not raw or raw == "--":
        return None
    parts = raw.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0.0, parts[0], parts[1]
    else:
        return None
    return round(h * 60 + m + s / 60.0, 2)


def _parse_garmin_float(raw: str) -> float | None:
    raw = (raw or "").strip().replace(",", "")
    if not raw or raw == "--":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def is_garmin_activities_csv(csv_path: Path) -> bool:
    """Sniff the header row to distinguish a Garmin Connect export from the
    generic date/metric/value CSV format — both are plain .csv files."""
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh), [])
    except (OSError, StopIteration):
        return False
    lower_header = {h.strip().lower() for h in header}
    return all(marker in lower_header for marker in _GARMIN_HEADER_MARKERS)


def _import_garmin_csv(
    root: Path, person_id: str, csv_path: Path, distance_unit: str = "km"
) -> dict[str, int]:
    """Import a Garmin Connect activities export into `workouts`.

    Distance is recorded in whichever unit the account was configured in when the
    file was exported (Garmin's CSV does not encode the unit) — pass
    distance_unit="mi" if the export is in miles. Pace is left for run_summary()'s
    existing distance/duration fallback rather than parsed from Garmin's own
    (equally unit-ambiguous) "Avg Pace" column.
    """
    counts: dict[str, int] = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_date = _row_get(row, "Date")
            if not raw_date:
                continue
            d = raw_date[:10]

            record: dict[str, Any] = {
                "type": _normalize_garmin_type(_row_get(row, "Activity Type")),
                "date": d,
            }

            distance = _parse_garmin_float(_row_get(row, "Distance"))
            if distance is not None:
                record["distance_km"] = round(
                    distance * 1.60934 if distance_unit == "mi" else distance, 3
                )

            duration = _parse_garmin_duration_min(_row_get(row, "Time", "Moving Time"))
            if duration is not None:
                record["duration_min"] = duration

            hr = _parse_garmin_float(_row_get(row, "Avg HR"))
            if hr is not None:
                record["hr_avg"] = hr

            calories = _parse_garmin_float(_row_get(row, "Calories"))
            if calories is not None:
                record["calories"] = calories

            title = _row_get(row, "Title")
            if title:
                record["notes"] = title

            upsert_record(
                root, person_id, "workouts", record,
                source_type="wearable", source_label="Garmin Connect", source_date=d,
            )
            counts[record["type"]] = counts.get(record["type"], 0) + 1

    return counts


def _import_csv(root: Path, person_id: str, csv_path: Path) -> dict[str, int]:
    """Generic CSV: columns date,metric,value[,unit]. Tolerant of extras."""
    counts: dict[str, int] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            d = row.get("date") or row.get("Date") or ""
            metric = (row.get("metric") or row.get("Metric") or "").strip().lower()
            try:
                value = float(row.get("value") or row.get("Value") or "")
            except (TypeError, ValueError):
                continue
            unit = (row.get("unit") or row.get("Unit") or "").strip()
            if not d or not metric:
                continue
            d = d[:10]
            if metric in ("weight", "weight_kg"):
                if unit.startswith("lb"):
                    value = value * 0.453592
                record_weight(root, person_id, d, value, "kg", csv_path.name)
                counts["weight"] = counts.get("weight", 0) + 1
            elif metric in ("steps", "heart_rate", "rhr", "vo2_max", "spo2", "hrv"):
                metric_norm = "heart_rate" if metric == "rhr" else metric
                record_vital(root, person_id, d, metric_norm, str(value), unit, csv_path.name)
                counts[metric_norm] = counts.get(metric_norm, 0) + 1
    return counts


# Health Auto Export metric names → internal mapping
# https://www.healthexportapp.com/
_HAE_METRIC_MAP = {
    "step_count":                     ("vital", "steps", ""),
    "resting_heart_rate":             ("vital", "heart_rate", "bpm"),
    "heart_rate":                     ("vital", "heart_rate", "bpm"),
    "heart_rate_variability_sdnn":    ("vital", "hrv", "ms"),
    "vo2_max":                        ("vital", "vo2_max", "ml/kg/min"),
    "oxygen_saturation":              ("vital", "spo2", "%"),
    "body_mass":                      ("weight", "weight", "kg"),
    "blood_pressure_systolic":        ("bp", "systolic", "mmHg"),
    "blood_pressure_diastolic":       ("bp", "diastolic", "mmHg"),
    "sleep_analysis":                 ("sleep", "sleep_hours", "h"),
}


def _import_health_auto_export_json(root: Path, person_id: str, json_path: Path) -> dict[str, int]:
    """Parse a Health Auto Export JSON file.

    The app exports data in this structure:
      {"data": {"metrics": [{"name": "step_count", "units": "count",
                              "data": [{"date": "2024-01-15 ...", "qty": 8421}]}, ...]}}

    Sleep uses inBed/asleep keys instead of qty.
    Blood pressure has systolicValue/diastolicValue keys.
    """
    import json as _json

    try:
        raw = _json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError) as e:
        raise ValueError(f"Cannot parse {json_path.name}: {e}") from e

    metrics = raw.get("data", {}).get("metrics", [])
    counts: dict[str, int] = {}
    daily_vitals: dict[tuple[str, date], list[float]] = {}
    bp_pairs: dict[date, dict[str, float]] = {}
    sleep_per_day: dict[date, float] = {}

    for metric_block in metrics:
        name = metric_block.get("name", "")
        mapping = _HAE_METRIC_MAP.get(name)
        if not mapping:
            continue
        kind, metric, unit = mapping
        units_override = metric_block.get("units", unit)

        for entry in metric_block.get("data", []):
            d = _parse_apple_date(entry.get("date", ""))
            if not d:
                continue

            if kind == "sleep":
                hours = float(entry.get("asleep") or entry.get("inBed") or 0)
                if hours > 0:
                    sleep_per_day[d] = max(sleep_per_day.get(d, 0.0), hours)
                continue

            if kind == "weight":
                raw_val = entry.get("qty")
                if raw_val is None:
                    continue
                kg_val = float(raw_val)
                if units_override.lower().startswith("lb"):
                    kg_val *= 0.453592
                record_weight(root, person_id, d.isoformat(), kg_val, "kg", "Health Auto Export")
                counts["weight"] = counts.get("weight", 0) + 1
                continue

            if kind == "bp":
                sys_val = entry.get("systolicValue") or entry.get("qty")
                dia_val = entry.get("diastolicValue")
                if metric == "systolic" and sys_val:
                    bp_pairs.setdefault(d, {})["systolic"] = float(sys_val)
                elif metric == "diastolic" and dia_val:
                    bp_pairs.setdefault(d, {})["diastolic"] = float(dia_val)
                elif sys_val and dia_val:
                    bp_pairs.setdefault(d, {})["systolic"] = float(sys_val)
                    bp_pairs.setdefault(d, {})["diastolic"] = float(dia_val)
                continue

            # kind == "vital"
            qty = entry.get("qty")
            if qty is None:
                continue
            daily_vitals.setdefault((metric, d), []).append(float(qty))

    # Flush daily vitals
    for (metric, d), values in daily_vitals.items():
        agg = sum(values) if metric == "steps" else sum(values) / len(values)
        u = "bpm" if metric == "heart_rate" else "ml/kg/min" if metric == "vo2_max" else "%" if metric == "spo2" else "ms" if metric == "hrv" else ""
        record_vital(root, person_id, d.isoformat(), metric, str(agg), u, "Health Auto Export")
        counts[metric] = counts.get(metric, 0) + 1

    # Flush BP
    for d, parts in bp_pairs.items():
        sys = parts.get("systolic")
        dia = parts.get("diastolic")
        if sys and dia:
            record_vital(root, person_id, d.isoformat(), "blood_pressure",
                         f"{int(sys)}/{int(dia)}", "mmHg", "Health Auto Export")
            counts["blood_pressure"] = counts.get("blood_pressure", 0) + 1

    # Flush sleep
    if sleep_per_day:
        with workspace_lock(root, person_id):
            profile = load_profile(root, person_id)
            checkins = list(profile.get("daily_checkins", []))
            existing_dates = {str(c.get("date", ""))[:10] for c in checkins}
            for d, hours in sleep_per_day.items():
                if d.isoformat() not in existing_dates:
                    checkins.append({
                        "date": d.isoformat(),
                        "sleep_hours": round(hours, 1),
                        "notes": "imported from Health Auto Export",
                    })
            profile["daily_checkins"] = sorted(checkins, key=lambda c: str(c.get("date", "")))
            save_profile(root, person_id, profile)
        counts["sleep"] = len(sleep_per_day)

    return counts


def import_wearable_file(
    root: Path, person_id: str, file_path: Path, distance_unit: str = "km"
) -> dict[str, int]:
    """Detect format and import. Returns counts of records added per metric.

    distance_unit only affects Garmin CSV imports (their export doesn't encode
    the account's unit setting) — pass "mi" if the export was made in miles.
    """
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    name = file_path.name.lower()
    if name.endswith(".xml"):
        return _import_apple_xml(root, person_id, file_path)
    if name.endswith(".csv"):
        if is_garmin_activities_csv(file_path):
            return _import_garmin_csv(root, person_id, file_path, distance_unit)
        return _import_csv(root, person_id, file_path)
    if name.endswith(".json"):
        return _import_health_auto_export_json(root, person_id, file_path)
    raise ValueError(f"Unsupported wearable file format: {file_path.suffix}")
