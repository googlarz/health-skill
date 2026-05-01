#!/usr/bin/env python3
"""
PostToolUse:Read hook — detect health data in file contents read by Claude.

Catches: lab CSV exports, workout exports, wearable data files, etc.
Uses the date extracted from file content for timeline integrity.
Appends findings to /tmp/health-ingest-{session_id}.json for Stop hook display.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Re-use helpers from health-auto-ingest
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("health_auto_ingest", Path(__file__).parent / "health-auto-ingest.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify
find_workspace = _mod.find_workspace
find_person_id = _mod.find_person_id
_load_health_scripts = _mod._load_health_scripts
insert_ctx_events = _mod.insert_ctx_events
_WEIGHT_SIGNALS = _mod._WEIGHT_SIGNALS


_HEALTH_FILE_EXTS = {".csv", ".txt", ".md", ".json", ".xml"}
_HEALTH_FILENAME_SIGNALS = re.compile(
    r"(lab|blood|workout|training|run|health|suunto|garmin|apple.health|export|results?)",
    re.IGNORECASE,
)


def is_health_file(file_path: str, content: str) -> bool:
    p = Path(file_path)
    if p.suffix.lower() not in _HEALTH_FILE_EXTS:
        return False
    if _HEALTH_FILENAME_SIGNALS.search(p.name):
        return True
    # Classify content
    return bool(classify(content[:500]))


def extract_date_from_content(content: str) -> str:
    """Try to find a date in the file content for timeline accuracy."""
    # ISO date
    m = re.search(r"\b(20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b", content)
    if m:
        return m.group(1)
    # DD/MM/YYYY or MM/DD/YYYY — less reliable, skip ambiguous
    return ""


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        return

    tool_input = data.get("tool_input") or {}
    tool_response = data.get("tool_response") or ""

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    # tool_response for Read is the file content as a string
    if isinstance(tool_response, dict):
        content = tool_response.get("content") or tool_response.get("text") or str(tool_response)
    else:
        content = str(tool_response)

    if not content or len(content) < 20:
        return

    if not is_health_file(file_path, content):
        return

    session_id = data.get("session_id", "")
    project_dir = data.get("cwd") or data.get("project_dir") or ""

    root = find_workspace(data)
    if not root:
        return

    person_id = find_person_id(root)
    _load_health_scripts(root)

    types = classify(content[:2000])
    if not types:
        return

    file_date = extract_date_from_content(content)
    from datetime import date as _date
    today = _date.today().isoformat()
    use_date = file_date or today

    saved = []
    ctx_events = []

    if "labs" in types:
        try:
            from extraction import extract_lab_candidates
            from care_workspace import upsert_record
            candidates = extract_lab_candidates(content, use_date)
            auto = [c for c in candidates if c.get("auto_apply")]
            for c in auto:
                upsert_record(root, person_id, "recent_tests", c["candidate"],
                              source_type="file-read", source_label=Path(file_path).name,
                              source_date=c["candidate"].get("date", use_date))
            if auto:
                names = ", ".join(
                    f"{c['candidate']['name']} {c['candidate']['value']}{c['candidate']['unit']}"
                    for c in auto[:4]
                )
                saved.append(f"🧪 Labs from {Path(file_path).name} [{use_date}]: {names}")
                ctx_events.append({
                    "type": "health_labs",
                    "category": "health",
                    "priority": 1,
                    "data": f"[{use_date}] labs from file: {names}",
                })
        except Exception:
            pass

    if "workout" in types:
        try:
            from training import parse_workout, log_workout
            workout = parse_workout(content[:1000])
            if workout.get("exercises") or workout.get("distance_km"):
                if file_date:
                    workout["date"] = file_date
                log_workout(root, person_id, workout)
                label = workout.get("type") or "workout"
                dist = workout.get("distance_km")
                dur = workout.get("duration_min")
                parts = [label]
                if dist:
                    parts.append(f"{dist}km")
                if dur:
                    parts.append(f"{dur}min")
                summary = " · ".join(str(p) for p in parts)
                saved.append(f"🏋️ Workout from {Path(file_path).name} [{use_date}]: {summary}")
                ctx_events.append({
                    "type": "health_workout",
                    "category": "health",
                    "priority": 1,
                    "data": f"[{use_date}] workout from file: {summary}",
                })
        except Exception:
            pass

    if "weight" in types:
        try:
            m = _WEIGHT_SIGNALS.search(content)
            if m:
                val = float(m.group(2))
                unit = "kg" if m.group(3).lower().startswith("k") else "lbs"
                from care_workspace import record_weight
                record_weight(root, person_id, use_date, val, unit)
                saved.append(f"⚖️ Weight from {Path(file_path).name} [{use_date}]: {val} {unit}")
                ctx_events.append({
                    "type": "health_weight",
                    "category": "health",
                    "priority": 2,
                    "data": f"[{use_date}] weight from file: {val} {unit}",
                })
        except Exception:
            pass

    if ctx_events and project_dir:
        insert_ctx_events(session_id, project_dir, ctx_events)

    if saved and session_id:
        summary_path = Path(f"/tmp/health-ingest-{session_id}.json")
        existing = []
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text()).get("lines", [])
            except Exception:
                pass
        summary_path.write_text(json.dumps({"lines": existing + saved}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
