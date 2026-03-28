#!/usr/bin/env python3
"""Workspace and record management helpers for Health Skill."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


SCHEMA_VERSION = 3


DEFAULT_PROFILE = {
    "schema_version": SCHEMA_VERSION,
    "person_id": "",
    "name": "",
    "date_of_birth": "",
    "sex": "",
    "conditions": [],
    "medications": [],
    "allergies": [],
    "clinicians": [],
    "recent_tests": [],
    "care_goals": [],
    "follow_up": [],
    "unresolved_questions": [],
    "documents": [],
    "encounters": [],
    "preferences": {
        "summary_style": "concise",
        "weight_unit": "kg",
        "primary_caregiver": "",
        "appointment_prep_style": "guided",
        "communication_tone": "calm",
        "preferred_clinicians": [],
    },
    "consents": {
        "workspace_storage": "user_requested",
        "minimum_necessary": True,
    },
    "audit": {
        "created_at": "",
        "updated_at": "",
        "conflicts_open": 0,
        "review_items_open": 0,
    },
}


RECORD_KEYS = {
    "conditions": ("name",),
    "medications": ("name",),
    "allergies": ("substance",),
    "clinicians": ("name", "role"),
    "recent_tests": ("name", "date"),
    "follow_up": ("task",),
    "care_goals": ("text",),
    "unresolved_questions": ("text",),
    "documents": ("title", "source_date"),
    "encounters": ("date", "kind", "title"),
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def humanize_name(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip()


def person_dir(root: Path, person_id: str) -> Path:
    return root if not person_id else root / "people" / person_id


def profile_path(root: Path, person_id: str) -> Path:
    filename = "HEALTH_PROFILE.json" if not person_id else "profile.json"
    return person_dir(root, person_id) / filename


def summary_path(root: Path, person_id: str) -> Path:
    filename = "HEALTH_SUMMARY.md" if not person_id else "summary.md"
    return person_dir(root, person_id) / filename


def dossier_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_DOSSIER.md"


def trends_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_TRENDS.md"


def home_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_HOME.md"


def weight_trends_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "WEIGHT_TRENDS.md"


def vitals_trends_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "VITALS_TRENDS.md"


def timeline_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_TIMELINE.md"


def change_report_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_CHANGE_REPORT.md"


def start_here_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "START_HERE.md"


def today_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "TODAY.md"


def this_week_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "THIS_WEEK.md"


def next_appointment_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "NEXT_APPOINTMENT.md"


def review_worklist_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "REVIEW_WORKLIST.md"


def care_status_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "CARE_STATUS.md"


def intake_summary_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "INTAKE_SUMMARY.md"


def assistant_update_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "ASSISTANT_UPDATE.md"


def conflicts_path(root: Path, person_id: str) -> Path:
    filename = "HEALTH_CONFLICTS.json" if not person_id else "conflicts.json"
    return person_dir(root, person_id) / filename


def review_queue_path(root: Path, person_id: str) -> Path:
    filename = "HEALTH_REVIEW_QUEUE.json" if not person_id else "review_queue.json"
    return person_dir(root, person_id) / filename


def medication_history_path(root: Path, person_id: str) -> Path:
    filename = "MEDICATION_HISTORY.json" if not person_id else "medication_history.json"
    return person_dir(root, person_id) / filename


def inbox_dir(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "inbox"


def archive_dir(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "Archive"


def notes_dir(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "notes"


def exports_dir(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "exports"


def reconciliation_path(root: Path, person_id: str) -> Path:
    return exports_dir(root, person_id) / "medication_reconciliation.md"


def calendar_export_path(root: Path, person_id: str) -> Path:
    return exports_dir(root, person_id) / "follow_up_calendar.ics"


def metrics_db_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "health_metrics.db"


def lock_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / ".health-skill.lock"


def normalize_list(section: str, items: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for item in items or []:
        if isinstance(item, dict):
            record = deepcopy(item)
        else:
            key = "text"
            if section == "conditions":
                key = "name"
            elif section == "medications":
                key = "name"
            elif section == "allergies":
                key = "substance"
            elif section == "follow_up":
                key = "task"
            elif section == "recent_tests":
                key = "name"
            elif section == "clinicians":
                key = "name"
            record = {key: str(item)}
        record.setdefault("source", {"type": "legacy", "label": "migrated data"})
        record.setdefault("last_updated", "")
        normalized.append(record)
    return normalized


def normalize_profile(profile: dict[str, Any], person_id: str = "") -> dict[str, Any]:
    normalized = deepcopy(DEFAULT_PROFILE)
    normalized.update({k: v for k, v in profile.items() if k in normalized})
    normalized["person_id"] = profile.get("person_id") or person_id or normalized["person_id"]
    normalized["name"] = profile.get("name", normalized["name"])
    normalized["date_of_birth"] = profile.get("date_of_birth", normalized["date_of_birth"])
    normalized["sex"] = profile.get("sex", normalized["sex"])

    for section in RECORD_KEYS:
        normalized[section] = normalize_list(section, profile.get(section, []))

    normalized["consents"] = {
        **DEFAULT_PROFILE["consents"],
        **profile.get("consents", {}),
    }
    normalized["preferences"] = {
        **DEFAULT_PROFILE["preferences"],
        **profile.get("preferences", {}),
    }
    normalized["audit"] = {
        **DEFAULT_PROFILE["audit"],
        **profile.get("audit", {}),
    }
    normalized["schema_version"] = SCHEMA_VERSION
    return normalized


def ensure_person(
    root: Path,
    person_id: str = "",
    name: str = "",
    date_of_birth: str = "",
    sex: str = "",
) -> Path:
    directory = person_dir(root, person_id)
    effective_person_id = person_id or slugify(name or root.name)
    notes_dir(root, person_id).mkdir(parents=True, exist_ok=True)
    inbox_dir(root, person_id).mkdir(parents=True, exist_ok=True)
    archive_dir(root, person_id).mkdir(parents=True, exist_ok=True)
    exports_dir(root, person_id).mkdir(parents=True, exist_ok=True)

    if not profile_path(root, person_id).exists():
        profile = deepcopy(DEFAULT_PROFILE)
        profile["person_id"] = effective_person_id
        profile["name"] = name
        profile["date_of_birth"] = date_of_birth
        profile["sex"] = sex
        profile["audit"]["created_at"] = now_utc()
        profile["audit"]["updated_at"] = profile["audit"]["created_at"]
        save_profile(root, person_id, profile)
    else:
        profile = load_profile(root, person_id)
        if name and not profile.get("name"):
            profile["name"] = name
        if date_of_birth and not profile.get("date_of_birth"):
            profile["date_of_birth"] = date_of_birth
        if sex and not profile.get("sex"):
            profile["sex"] = sex
        save_profile(root, person_id, profile)

    if not summary_path(root, person_id).exists():
        atomic_write_text(summary_path(root, person_id), "# Health Summary\n\nNot rendered yet.\n")

    if not dossier_path(root, person_id).exists():
        atomic_write_text(dossier_path(root, person_id), "# Health Dossier\n\nNot rendered yet.\n")

    if not trends_path(root, person_id).exists():
        atomic_write_text(trends_path(root, person_id), "# Health Trends\n\nNot rendered yet.\n")

    if not home_path(root, person_id).exists():
        atomic_write_text(home_path(root, person_id), "# Health Home\n\nNot rendered yet.\n")

    if not weight_trends_path(root, person_id).exists():
        atomic_write_text(weight_trends_path(root, person_id), "# Weight Trends\n\nNo weight entries yet.\n")

    if not vitals_trends_path(root, person_id).exists():
        atomic_write_text(vitals_trends_path(root, person_id), "# Vitals Trends\n\nNo vital entries yet.\n")

    if not timeline_path(root, person_id).exists():
        atomic_write_text(timeline_path(root, person_id), "# Health Timeline\n\nNot rendered yet.\n")

    if not change_report_path(root, person_id).exists():
        atomic_write_text(change_report_path(root, person_id), "# Health Change Report\n\nNot rendered yet.\n")

    if not start_here_path(root, person_id).exists():
        atomic_write_text(start_here_path(root, person_id), "# Start Here\n\nNot rendered yet.\n")

    if not today_path(root, person_id).exists():
        atomic_write_text(today_path(root, person_id), "# Today\n\nNot rendered yet.\n")

    if not this_week_path(root, person_id).exists():
        atomic_write_text(this_week_path(root, person_id), "# This Week\n\nNot rendered yet.\n")

    if not next_appointment_path(root, person_id).exists():
        atomic_write_text(next_appointment_path(root, person_id), "# Next Appointment\n\nNot rendered yet.\n")

    if not review_worklist_path(root, person_id).exists():
        atomic_write_text(review_worklist_path(root, person_id), "# Review Worklist\n\nNot rendered yet.\n")

    if not care_status_path(root, person_id).exists():
        atomic_write_text(care_status_path(root, person_id), "# Care Status\n\nNot rendered yet.\n")

    if not intake_summary_path(root, person_id).exists():
        atomic_write_text(intake_summary_path(root, person_id), "# Intake Summary\n\nNo intake activity yet.\n")

    if not assistant_update_path(root, person_id).exists():
        atomic_write_text(assistant_update_path(root, person_id), "# Assistant Update\n\nNo workspace actions recorded yet.\n")

    if not conflicts_path(root, person_id).exists():
        save_conflicts(root, person_id, [])

    if not review_queue_path(root, person_id).exists():
        save_review_queue(root, person_id, [])

    if not medication_history_path(root, person_id).exists():
        save_medication_history(root, person_id, [])

    return directory


def load_profile(root: Path, person_id: str) -> dict[str, Any]:
    path = profile_path(root, person_id)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found for person_id={person_id}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    return normalize_profile(profile, person_id=person_id)


def save_profile(root: Path, person_id: str, profile: dict[str, Any]) -> Path:
    normalized = normalize_profile(profile, person_id=person_id)
    normalized["audit"]["updated_at"] = now_utc()
    path = profile_path(root, person_id)
    atomic_write_text(path, json.dumps(normalized, indent=2) + "\n")
    return path


def load_conflicts(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = conflicts_path(root, person_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_conflicts(root: Path, person_id: str, conflicts: list[dict[str, Any]]) -> Path:
    path = conflicts_path(root, person_id)
    atomic_write_text(path, json.dumps(conflicts, indent=2) + "\n")
    return path


def load_review_queue(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = review_queue_path(root, person_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_review_queue(root: Path, person_id: str, items: list[dict[str, Any]]) -> Path:
    path = review_queue_path(root, person_id)
    atomic_write_text(path, json.dumps(items, indent=2) + "\n")
    return path


def load_medication_history(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = medication_history_path(root, person_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_medication_history(root: Path, person_id: str, items: list[dict[str, Any]]) -> Path:
    path = medication_history_path(root, person_id)
    atomic_write_text(path, json.dumps(items, indent=2) + "\n")
    return path


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)


def write_assistant_update(root: Path, person_id: str, title: str, bullets: list[str]) -> Path:
    path = assistant_update_path(root, person_id)
    atomic_write_text(path, render_assistant_update_text(title, bullets))
    return path


@contextlib.contextmanager
def workspace_lock(root: Path, person_id: str):
    path = lock_path(root, person_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def set_nested_field(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for key in parts[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[parts[-1]] = value


def source_metadata(
    source_type: str = "user",
    source_label: str = "",
    source_date: str = "",
) -> dict[str, str]:
    return {
        "type": source_type,
        "label": source_label,
        "date": source_date,
    }


def normalize_unit(unit: str) -> str:
    normalized = unit.strip()
    aliases = {
        "mg/dl": "mg/dL",
        "ma/dl": "mg/dL",
        "mmol/l": "mmol/L",
        "iu/l": "IU/L",
        "u/l": "U/L",
        "kg": "kg",
        "lb": "lb",
        "lbs": "lb",
    }
    return aliases.get(normalized.lower(), normalized)


def normalize_frequency(text: str) -> str:
    lowered = re.sub(r"\s+", " ", text.strip().lower())
    mapping = {
        "daily": "daily",
        "once daily": "daily",
        "nightly": "nightly",
        "twice daily": "twice daily",
        "bid": "twice daily",
        "tid": "three times daily",
        "prn": "as needed",
        "as needed": "as needed",
        "weekly": "weekly",
    }
    return mapping.get(lowered, lowered)


def normalize_section_record(section: str, record: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(record)
    if section == "recent_tests":
        if normalized.get("name"):
            normalized["name"] = normalize_test_name(str(normalized["name"]))
        if normalized.get("unit"):
            normalized["unit"] = normalize_unit(str(normalized["unit"]))
    elif section == "medications":
        if normalized.get("name"):
            normalized["name"] = title_case_name(str(normalized["name"]).strip().lower())
        if normalized.get("frequency"):
            normalized["frequency"] = normalize_frequency(str(normalized["frequency"]))
        if normalized.get("form"):
            normalized["form"] = str(normalized["form"]).strip().lower()
    elif section == "clinicians":
        if normalized.get("name"):
            normalized["name"] = title_case_name(str(normalized["name"]).strip().lower())
        if normalized.get("role"):
            normalized["role"] = title_case_name(str(normalized["role"]).strip().lower())
    return normalized


def prepare_record(
    section: str,
    value: Any,
    source_type: str = "user",
    source_label: str = "",
    source_date: str = "",
) -> dict[str, Any]:
    if isinstance(value, dict):
        record = deepcopy(value)
    else:
        default_key = RECORD_KEYS[section][0]
        record = {default_key: value}

    record["source"] = {
        **record.get("source", {}),
        **source_metadata(source_type, source_label, source_date),
    }
    record["last_updated"] = now_utc()
    return normalize_section_record(section, record)


def record_identity(section: str, record: dict[str, Any]) -> str:
    values = [str(record.get(key, "")).strip().lower() for key in RECORD_KEYS[section]]
    return "|".join(values)


def create_conflict(
    root: Path,
    person_id: str,
    section: str,
    identity: str,
    field: str,
    previous: Any,
    new_value: Any,
    source: dict[str, Any],
) -> None:
    conflicts = load_conflicts(root, person_id)
    conflict_id = f"{date.today().isoformat()}-{section}-{len(conflicts) + 1}"
    conflicts.append(
        {
            "id": conflict_id,
            "status": "open",
            "section": section,
            "identity": identity,
            "field": field,
            "previous": previous,
            "new_value": new_value,
            "source": source,
            "detected_at": now_utc(),
        }
    )
    save_conflicts(root, person_id, conflicts)


def sync_conflict_count(root: Path, person_id: str, profile: dict[str, Any]) -> None:
    conflicts = load_conflicts(root, person_id)
    profile["audit"]["conflicts_open"] = sum(1 for item in conflicts if item["status"] == "open")


def sync_review_count(root: Path, person_id: str, profile: dict[str, Any]) -> None:
    items = load_review_queue(root, person_id)
    profile["audit"]["review_items_open"] = sum(
        1 for item in items if item.get("status", "open") == "open"
    )


def append_medication_history(
    root: Path,
    person_id: str,
    medication_name: str,
    event_type: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    source: dict[str, Any],
) -> None:
    history = load_medication_history(root, person_id)
    history.append(
        {
            "recorded_at": now_utc(),
            "medication_name": medication_name,
            "event_type": event_type,
            "previous": previous or {},
            "current": current,
            "source": source,
        }
    )
    save_medication_history(root, person_id, history)


def ensure_metrics_db(root: Path, person_id: str) -> sqlite3.Connection:
    path = metrics_db_path(root, person_id)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS weight_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            note TEXT DEFAULT '',
            recorded_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vital_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            metric TEXT NOT NULL,
            value_text TEXT NOT NULL,
            unit TEXT DEFAULT '',
            note TEXT DEFAULT '',
            recorded_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def record_weight(
    root: Path,
    person_id: str,
    entry_date: str,
    value: float,
    unit: str,
    note: str = "",
) -> None:
    with ensure_metrics_db(root, person_id) as connection:
        connection.execute(
            """
            INSERT INTO weight_entries (entry_date, value, unit, note, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entry_date, value, unit, note, now_utc()),
        )
        connection.commit()


def load_weight_entries(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = metrics_db_path(root, person_id)
    if not path.exists():
        return []
    with ensure_metrics_db(root, person_id) as connection:
        rows = connection.execute(
            """
            SELECT entry_date, value, unit, note, recorded_at
            FROM weight_entries
            ORDER BY entry_date ASC, id ASC
            """
        ).fetchall()
    return [
        {
            "entry_date": row[0],
            "value": row[1],
            "unit": row[2],
            "note": row[3],
            "recorded_at": row[4],
        }
        for row in rows
    ]


def normalize_vital_metric(metric: str) -> str:
    lowered = metric.strip().lower()
    aliases = {
        "bp": "blood_pressure",
        "blood pressure": "blood_pressure",
        "spo2": "oxygen_saturation",
        "oxygen": "oxygen_saturation",
        "pulse": "heart_rate",
        "glucose": "glucose",
        "heart rate": "heart_rate",
        "sleep": "sleep_hours",
        "pain": "pain_score",
        "mood": "mood_score",
    }
    return aliases.get(lowered, lowered)


def record_vital(
    root: Path,
    person_id: str,
    entry_date: str,
    metric: str,
    value_text: str,
    unit: str = "",
    note: str = "",
) -> None:
    normalized_metric = normalize_vital_metric(metric)
    with ensure_metrics_db(root, person_id) as connection:
        connection.execute(
            """
            INSERT INTO vital_entries (entry_date, metric, value_text, unit, note, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_date, normalized_metric, value_text, unit, note, now_utc()),
        )
        connection.commit()


def load_vital_entries(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = metrics_db_path(root, person_id)
    if not path.exists():
        return []
    with ensure_metrics_db(root, person_id) as connection:
        rows = connection.execute(
            """
            SELECT entry_date, metric, value_text, unit, note, recorded_at
            FROM vital_entries
            ORDER BY entry_date ASC, id ASC
            """
        ).fetchall()
    return [
        {
            "entry_date": row[0],
            "metric": row[1],
            "value_text": row[2],
            "unit": row[3],
            "note": row[4],
            "recorded_at": row[5],
        }
        for row in rows
    ]


def upsert_record(
    root: Path,
    person_id: str,
    section: str,
    value: Any,
    source_type: str = "user",
    source_label: str = "",
    source_date: str = "",
) -> tuple[Path, dict[str, Any]]:
    profile = load_profile(root, person_id)
    record = prepare_record(section, value, source_type, source_label, source_date)
    identity = record_identity(section, record)

    items = profile[section]
    existing = None
    for item in items:
        if record_identity(section, item) == identity:
            existing = item
            break

    if existing is None:
        items.append(record)
        if section == "medications":
            append_medication_history(
                root,
                person_id,
                str(record.get("name", "")),
                "added",
                None,
                deepcopy(record),
                record["source"],
            )
    else:
        previous_snapshot = deepcopy(existing)
        for field, new_value in record.items():
            if field in {"source", "last_updated"}:
                continue
            old_value = existing.get(field)
            if old_value not in (None, "", [], {}) and new_value not in (None, "", [], {}) and old_value != new_value:
                create_conflict(
                    root,
                    person_id,
                    section,
                    identity,
                    field,
                    old_value,
                    new_value,
                    record["source"],
                )
            if new_value not in (None, "", [], {}):
                existing[field] = new_value
        existing["source"] = record["source"]
        existing["last_updated"] = record["last_updated"]
        if section == "medications" and previous_snapshot != existing:
            append_medication_history(
                root,
                person_id,
                str(existing.get("name", "")),
                "updated",
                previous_snapshot,
                deepcopy(existing),
                record["source"],
            )

    sync_conflict_count(root, person_id, profile)
    sync_review_count(root, person_id, profile)
    path = save_profile(root, person_id, profile)
    return path, record


def add_note(
    root: Path,
    person_id: str,
    title: str,
    body: str,
    source_type: str = "user",
    source_label: str = "",
    source_date: str = "",
) -> Path:
    ensure_person(root, person_id)
    note_slug = slugify(title)
    filename = f"{date.today().isoformat()}-{note_slug}.md"
    note_path = notes_dir(root, person_id) / filename
    metadata = [
        f"- Source type: {source_type or 'user'}",
        f"- Source label: {source_label or 'not provided'}",
        f"- Source date: {source_date or 'not provided'}",
        f"- Captured at: {now_utc()}",
    ]
    note_text = f"# {title}\n\n" + "\n".join(metadata) + f"\n\n{body.strip()}\n"
    atomic_write_text(note_path, note_text)
    return note_path


def document_preview(document_path: Path) -> str:
    suffix = document_path.suffix.lower()
    raw_text, mode = read_document_text_with_mode(document_path)
    if not raw_text:
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"} and Image is not None:
            try:
                with Image.open(document_path) as image:
                    return (
                        f"Image stored ({image.width}x{image.height}). OCR is unavailable in this environment. "
                        "Manual review required."
                    )
            except Exception:
                pass
        if suffix == ".pdf":
            return "PDF stored but no extractable text was found. It may be scanned; OCR is unavailable here."
        return "Binary or unsupported document stored. Manual review required."

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    preview = " ".join(lines[:12])
    preview = re.sub(r"\s+", " ", preview).strip()
    if len(preview) > 500:
        preview = preview[:497] + "..."
    if mode in {"image_ocr", "pdf_ocr"}:
        preview = f"[OCR] {preview}"
    return preview or "Document ingested with no extractable text preview."


def run_apple_ocr(path: Path) -> str:
    swift_path = Path(__file__).with_name("apple_ocr.swift")
    if not swift_path.exists():
        return ""
    try:
        completed = subprocess.run(
            ["/usr/bin/swift", str(swift_path), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (completed.stdout or "").strip()


def infer_doc_type(source_path: Path) -> str:
    name = source_path.name.lower()
    if any(token in name for token in ("lab", "cbc", "lipid", "a1c", "blood")):
        return "lab"
    if any(token in name for token in ("discharge", "after-visit", "avs")):
        return "discharge"
    if any(token in name for token in ("med", "medication", "rx", "prescription")):
        return "medication-list"
    if any(token in name for token in ("imaging", "xray", "mri", "ct", "ultrasound")):
        return "imaging"
    if any(token in name for token in ("visit", "consult", "follow-up", "followup")):
        return "visit-note"
    if any(token in name for token in ("plan", "care-plan")):
        return "care-plan"
    return "document"


def is_in_inbox(root: Path, person_id: str, source_path: Path) -> bool:
    try:
        return source_path.resolve().is_relative_to(inbox_dir(root, person_id).resolve())
    except ValueError:
        return False


def list_inbox_files(root: Path, person_id: str) -> list[Path]:
    directory = inbox_dir(root, person_id)
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())


def supported_text_document(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".txt", ".json", ".pdf"}


def read_document_text_with_mode(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace"), "text"
    if suffix == ".pdf":
        if pdfplumber is not None:
            try:
                with pdfplumber.open(path) as pdf:
                    text = "\n".join((page.extract_text() or "") for page in pdf.pages[:10]).strip()
                if text:
                    return text, "pdf_text"
            except Exception:
                pass
        if PdfReader is not None:
            try:
                reader = PdfReader(str(path))
                text = "\n".join((page.extract_text() or "") for page in reader.pages[:10]).strip()
                if text:
                    return text, "pdf_text"
            except Exception:
                pass
        ocr_text = run_apple_ocr(path)
        return ocr_text, "pdf_ocr" if ocr_text else "none"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        ocr_text = run_apple_ocr(path)
        return ocr_text, "image_ocr" if ocr_text else "none"
    return "", "none"


def read_document_text(path: Path) -> str:
    return read_document_text_with_mode(path)[0]


def title_case_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def normalize_test_name(name: str) -> str:
    compact = re.sub(r"\s+", " ", name.strip()).lower()
    aliases = {
        "ldl": "LDL",
        "hdl": "HDL",
        "a1c": "A1C",
        "hba1c": "A1C",
        "tsh": "TSH",
        "bun": "BUN",
        "alt": "ALT",
        "ast": "AST",
    }
    return aliases.get(compact, title_case_name(compact))


def normalize_lab_flag(flag: str) -> str:
    lowered = flag.strip().lower()
    mapping = {
        "h": "high",
        "high": "high",
        "l": "low",
        "low": "low",
        "n": "normal",
        "normal": "normal",
        "abnormal": "abnormal",
    }
    return mapping.get(lowered, lowered)


def interpret_against_range(value: float, low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return ""
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "in_range"


def extract_lab_candidates(raw_text: str, source_date: str) -> list[dict[str, Any]]:
    candidates = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9 ()/%+-]{1,40}?)\s+(-?\d+(?:\.\d+)?)\s*([A-Za-z%/]+)"
            r"(?:\s*\(?\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*\)?)?"
            r"(?:\s+([HLN]|high|low|normal|abnormal))?\s*$",
            stripped,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        name, value, unit, low, high, raw_flag = match.groups()
        if len(name.strip()) < 2:
            continue
        numeric_value = float(value)
        low_value = float(low) if low is not None else None
        high_value = float(high) if high is not None else None
        normalized_flag = (
            normalize_lab_flag(raw_flag) if raw_flag else interpret_against_range(numeric_value, low_value, high_value)
        )
        reference_range = ""
        if low is not None and high is not None:
            reference_range = f"{low}-{high} {unit}"
        candidates.append(
            {
                "section": "recent_tests",
                "candidate": {
                    "name": normalize_test_name(name),
                    "value": value,
                    "unit": unit,
                    "date": source_date,
                    "reference_range": reference_range,
                    "flag": normalized_flag,
                    "interpretation": normalized_flag,
                },
                "confidence": "high",
                "auto_apply": True,
                "rationale": "Structured lab-style line detected in source document.",
                "source_snippet": stripped,
            }
        )
    return candidates


def extract_medication_candidates(raw_text: str, doc_type: str) -> list[dict[str, Any]]:
    candidates = []
    lab_like_names = {"ldl", "hdl", "a1c", "hba1c", "tsh", "bun", "alt", "ast"}
    frequency_tokens = {
        "daily": "daily",
        "nightly": "nightly",
        "weekly": "weekly",
        "bid": "twice daily",
        "tid": "three times daily",
        "prn": "as needed",
        "as needed": "as needed",
    }
    form_tokens = {"tablet", "capsule", "inhaler", "patch", "solution", "cream", "spray"}
    for line in raw_text.splitlines():
        match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9/-]*(?: [A-Za-z0-9/-]+){0,3})\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\b(.*)$",
            line.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        name, amount, unit, remainder = match.groups()
        if "/" in remainder or name.strip().lower() in lab_like_names:
            continue
        dose = f"{amount} {unit}{remainder}".strip()
        lowered_remainder = remainder.lower()
        frequency = ""
        form = ""
        for token, normalized in frequency_tokens.items():
            if token in lowered_remainder:
                frequency = normalized
                break
        for token in form_tokens:
            if token in lowered_remainder:
                form = token
                break
        candidates.append(
            {
                "section": "medications",
                "candidate": {
                    "name": title_case_name(name.strip().lower()),
                    "dose": re.sub(r"\s+", " ", dose),
                    "form": form,
                    "frequency": frequency,
                    "status": "needs-confirmation",
                },
                "confidence": "high" if doc_type == "medication-list" else "medium",
                "auto_apply": doc_type == "medication-list",
                "rationale": "Medication-style line with dose detected in source document.",
                "source_snippet": line.strip(),
            }
        )
    return candidates


def extract_follow_up_candidates(raw_text: str) -> list[dict[str, Any]]:
    candidates = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if "follow up" in lowered or "follow-up" in lowered or lowered.startswith("next:"):
            candidates.append(
                {
                    "section": "follow_up",
                    "candidate": {
                        "task": stripped,
                        "status": "needs-review",
                    },
                    "confidence": "medium",
                    "auto_apply": False,
                    "rationale": "Follow-up style instruction detected in source document.",
                    "source_snippet": stripped,
                }
            )
    return candidates[:5]


def extract_candidates_from_document(
    path: Path,
    doc_type: str,
    source_date: str,
) -> list[dict[str, Any]]:
    raw_text, mode = read_document_text_with_mode(path)
    if not raw_text:
        return []

    candidates = []
    if doc_type in {"lab", "document"}:
        candidates.extend(extract_lab_candidates(raw_text, source_date))
    candidates.extend(extract_medication_candidates(raw_text, doc_type))
    candidates.extend(extract_follow_up_candidates(raw_text))
    if mode in {"image_ocr", "pdf_ocr"}:
        for item in candidates:
            item["auto_apply"] = False
            item["confidence"] = "medium" if item.get("confidence") == "high" else item.get("confidence", "medium")
            item["rationale"] = item.get("rationale", "") + " Extracted via OCR; confirm before trusting."
    return candidates


def add_review_items(
    root: Path,
    person_id: str,
    items: list[dict[str, Any]],
    source_title: str,
    source_date: str,
) -> list[dict[str, Any]]:
    queue = load_review_queue(root, person_id)
    created = []
    for item in items:
        review_id = f"{date.today().isoformat()}-review-{len(queue) + 1}"
        review_item = {
            "id": review_id,
            "status": "open",
            "applied": item.get("auto_apply", False),
            "section": item["section"],
            "candidate": item["candidate"],
            "confidence": item.get("confidence", "medium"),
            "tier": review_tier_for_item(item),
            "rationale": item.get("rationale", ""),
            "source_snippet": item.get("source_snippet", ""),
            "source_title": source_title,
            "source_date": source_date,
            "detected_at": now_utc(),
        }
        queue.append(review_item)
        created.append(review_item)
    save_review_queue(root, person_id, queue)
    return created


def process_extracted_candidates(
    root: Path,
    person_id: str,
    source_title: str,
    source_date: str,
    extracted_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    created = add_review_items(root, person_id, extracted_items, source_title, source_date)
    for item in extracted_items:
        if item.get("auto_apply"):
            upsert_record(
                root,
                person_id,
                item["section"],
                item["candidate"],
                source_type="document-extraction",
                source_label=source_title,
                source_date=source_date,
            )
    return created


def review_tier_for_item(item: dict[str, Any]) -> str:
    if item.get("auto_apply"):
        return "safe_to_auto_apply"
    confidence = item.get("confidence", "medium")
    if confidence == "high":
        return "needs_quick_confirmation"
    return "do_not_trust_without_human_review"


def ingest_document(
    root: Path,
    person_id: str,
    source_path: Path,
    doc_type: str,
    title: str = "",
    source_date: str = "",
) -> tuple[Path, Path]:
    ensure_person(root, person_id)
    normalized_source_date = source_date or date.today().isoformat()
    safe_title = title or humanize_name(source_path.stem)
    destination_name = f"{date.today().isoformat()}-{slugify(safe_title)}{source_path.suffix.lower()}"
    destination_path = archive_dir(root, person_id) / destination_name
    if is_in_inbox(root, person_id, source_path):
        shutil.move(str(source_path), str(destination_path))
        ingest_mode = "moved_from_inbox"
    else:
        shutil.copy2(source_path, destination_path)
        ingest_mode = "copied"

    preview = document_preview(destination_path)
    extracted_items = extract_candidates_from_document(
        destination_path,
        doc_type,
        normalized_source_date,
    )
    processed_reviews = process_extracted_candidates(
        root,
        person_id,
        safe_title,
        normalized_source_date,
        extracted_items,
    )
    record = {
        "title": safe_title,
        "doc_type": doc_type,
        "source_date": normalized_source_date,
        "original_path": str(source_path),
        "archived_path": str(destination_path),
        "ingest_mode": ingest_mode,
        "review_required": True,
        "review_queue_items": [item["id"] for item in processed_reviews],
        "preview_excerpt": preview,
    }
    upsert_record(
        root,
        person_id,
        "documents",
        record,
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    upsert_record(
        root,
        person_id,
        "encounters",
        {
            "date": normalized_source_date,
            "kind": doc_type,
            "title": safe_title,
            "summary": preview,
        },
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    note_path = add_note(
        root,
        person_id,
        f"Document ingest: {safe_title}",
        f"Document type: {doc_type}\n\nPreview:\n{preview}\n\n"
        f"Extraction candidates created: {len(processed_reviews)}\n\n"
        "Manual review required before relying on extracted facts.",
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    return destination_path, note_path


def process_inbox(root: Path, person_id: str) -> list[tuple[Path, Path]]:
    ensure_person(root, person_id)
    processed = []
    for source_path in list_inbox_files(root, person_id):
        archived_path, note_path = ingest_document(
            root,
            person_id,
            source_path,
            infer_doc_type(source_path),
            title=humanize_name(source_path.stem),
            source_date="",
        )
        processed.append((archived_path, note_path))
    return processed


def render_record(record: dict[str, Any], preferred_fields: tuple[str, ...]) -> str:
    rendered = []
    for field in preferred_fields:
        value = record.get(field)
        if value:
            rendered.append(str(value))
    if rendered:
        return " | ".join(rendered)
    for key, value in record.items():
        if key not in {"source", "last_updated"} and value not in (None, "", [], {}):
            return f"{key}: {value}"
    return "none recorded"


def render_list(items: list[dict[str, Any]], preferred_fields: tuple[str, ...]) -> str:
    if not items:
        return "- none recorded"
    return "\n".join(f"- {render_record(item, preferred_fields)}" for item in items)


def source_trust_label(source: dict[str, Any] | None) -> str:
    source = source or {}
    source_type = str(source.get("type") or "").strip().lower()
    label = str(source.get("label") or "").strip()

    mapping = {
        "document": "confirmed from source document",
        "document-extraction": "document-derived and should be reviewed",
        "review-application": "accepted after review",
        "user": "user-reported",
        "legacy": "migrated from older records",
    }
    base = mapping.get(source_type, "source needs review")
    if label:
        return f"{base} ({label})"
    return base


def source_trust_reason(source: dict[str, Any] | None) -> str:
    source = source or {}
    source_type = str(source.get("type") or "").strip().lower()
    reasons = {
        "document": "Based on a stored source file rather than memory alone.",
        "document-extraction": "Pulled from a document automatically, so it still deserves a human check.",
        "review-application": "Promoted into the record after explicit review.",
        "user": "Comes from a direct user or caregiver report.",
        "legacy": "Carried forward from older workspace data.",
    }
    return reasons.get(source_type, "The source is not clear enough yet.")


def review_source_snippet(item: dict[str, Any]) -> str:
    snippet = str(item.get("source_snippet") or "").strip()
    if not snippet:
        return ""
    return re.sub(r"\s+", " ", snippet)[:180]


def review_trust_label(item: dict[str, Any]) -> str:
    tier = item.get("tier")
    confidence = item.get("confidence", "medium")
    if tier == "safe_to_auto_apply":
        return f"Probably safe to accept ({confidence} confidence)"
    if tier == "needs_quick_confirmation":
        return f"Quick confirmation recommended ({confidence} confidence)"
    return f"Do not trust without a human check ({confidence} confidence)"


def status_chip(ok: bool, positive: str, needs_attention: str) -> str:
    return positive if ok else needs_attention


def open_reviews(review_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in review_queue if item.get("status", "open") == "open"]


def open_conflicts_only(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in conflicts if item.get("status") == "open"]


def pending_follow_ups(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in profile.get("follow_up", [])
        if item.get("status") != "done"
    ]


def due_follow_ups(profile: dict[str, Any], days: int = 0) -> list[dict[str, Any]]:
    today = date.today()
    due_items = []
    for item in pending_follow_ups(profile):
        due_date = parse_date_like(str(item.get("due_date") or ""))
        if not due_date:
            continue
        if (due_date.date() - today).days <= days:
            due_items.append(item)
    return sorted(due_items, key=lambda item: item.get("due_date", ""))


def completed_follow_up_count(profile: dict[str, Any]) -> int:
    return sum(1 for item in profile.get("follow_up", []) if item.get("status") == "done")


def next_follow_up(profile: dict[str, Any]) -> dict[str, Any] | None:
    dated = [
        item
        for item in pending_follow_ups(profile)
        if item.get("due_date")
    ]
    if not dated:
        return None
    return sorted(dated, key=lambda item: item.get("due_date", ""))[0]


def record_with_trust(record: dict[str, Any], preferred_fields: tuple[str, ...]) -> str:
    detail = render_record(record, preferred_fields)
    return f"{detail} | trust: {source_trust_label(record.get('source'))}"


def render_list_with_trust(items: list[dict[str, Any]], preferred_fields: tuple[str, ...], limit: int = 10) -> str:
    if not items:
        return "- none recorded"
    return "\n".join(f"- {record_with_trust(item, preferred_fields)}" for item in items[:limit])


def latest_recent_tests(profile: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return sorted(
        profile.get("recent_tests", []),
        key=lambda item: item.get("date", ""),
        reverse=True,
    )[:limit]


def recent_abnormal_tests(profile: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    items = [
        item
        for item in profile.get("recent_tests", [])
        if item.get("flag") in {"high", "low", "abnormal"}
    ]
    return sorted(items, key=lambda item: item.get("date", ""), reverse=True)[:limit]


def current_priorities(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
) -> list[str]:
    priorities = []
    open_conflicts = open_conflicts_only(conflicts)
    open_review_items = open_reviews(review_queue)
    due_now = due_follow_ups(profile, days=0)
    due_this_week = due_follow_ups(profile, days=7)
    abnormal = recent_abnormal_tests(profile, limit=3)

    if inbox_files:
        priorities.append(f"Process {len(inbox_files)} file(s) sitting in inbox.")
    if due_now:
        priorities.append(f"Handle {len(due_now)} follow-up item(s) due now or overdue.")
    elif due_this_week:
        priorities.append(f"Plan for {len(due_this_week)} follow-up item(s) due within 7 days.")
    if open_review_items:
        priorities.append(f"Review {len(open_review_items)} extracted item(s) before relying on them.")
    if open_conflicts:
        priorities.append(f"Resolve {len(open_conflicts)} source conflict(s) so the record is trustworthy.")
    if abnormal:
        priorities.append(
            "Keep an eye on abnormal labs: "
            + ", ".join(f"{item.get('name')} {item.get('value')} {item.get('unit', '')}".strip() for item in abnormal)
        )
    if not priorities:
        priorities.append("No urgent workspace cleanup is needed right now.")
    return priorities[:5]


def preferences_summary(profile: dict[str, Any]) -> list[str]:
    preferences = profile.get("preferences", {})
    lines = [
        f"Summary style: {preferences.get('summary_style') or 'concise'}",
        f"Preferred weight unit: {preferences.get('weight_unit') or 'kg'}",
        f"Communication tone: {preferences.get('communication_tone') or 'calm'}",
        f"Appointment prep style: {preferences.get('appointment_prep_style') or 'guided'}",
    ]
    if preferences.get("primary_caregiver"):
        lines.append(f"Primary caregiver: {preferences['primary_caregiver']}")
    if preferences.get("preferred_clinicians"):
        preferred = ", ".join(str(item) for item in preferences["preferred_clinicians"])
        lines.append(f"Preferred clinicians: {preferred}")
    return lines


def care_success_markers(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
) -> list[str]:
    open_conflicts = open_conflicts_only(conflicts)
    open_review_items = open_reviews(review_queue)
    markers = [
        status_chip(not inbox_files, "Inbox is clear.", f"Inbox has {len(inbox_files)} file(s) waiting."),
        status_chip(
            not open_review_items,
            "No extracted facts are waiting for review.",
            f"{len(open_review_items)} extracted fact(s) still need review.",
        ),
        status_chip(
            not open_conflicts,
            "No source conflicts are open.",
            f"{len(open_conflicts)} source conflict(s) still need resolution.",
        ),
        status_chip(
            bool(profile.get("medications")),
            "Medication list exists.",
            "Medication list still needs to be built or confirmed.",
        ),
        status_chip(
            bool(next_follow_up(profile)),
            "A next follow-up is recorded.",
            "No dated follow-up is recorded yet.",
        ),
    ]
    return markers


def render_summary_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
) -> str:
    open_conflict_items = open_conflicts_only(conflicts)
    open_review_items = open_reviews(review_queue)
    priorities = current_priorities(profile, conflicts, inbox_files, review_queue)
    lines = [
        "# Health Summary",
        "",
        f"- Person ID: `{profile.get('person_id') or 'unknown'}`",
        f"- Name: {profile.get('name') or 'unknown'}",
        f"- Date of birth: {profile.get('date_of_birth') or 'unknown'}",
        f"- Sex: {profile.get('sex') or 'unknown'}",
        f"- Schema version: {profile.get('schema_version')}",
        f"- Last updated: {profile.get('audit', {}).get('updated_at') or 'unknown'}",
        f"- Pending inbox files: {len(inbox_files)}",
        f"- Review queue items: {len(open_review_items)}",
        f"- Latest weight: {latest_weight_summary(weight_entries)}",
        "",
        "## What Matters Most",
    ]
    lines.extend(f"- {item}" for item in priorities)
    lines.extend(
        [
            "",
            "## Confidence And Progress",
        ]
    )
    lines.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    lines.extend(
        [
            "",
            "## Conditions",
            render_list_with_trust(profile.get("conditions", []), ("name", "status")),
            "",
            "## Medications",
            render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
            "",
            "## Allergies",
            render_list_with_trust(profile.get("allergies", []), ("substance", "reaction", "severity")),
            "",
            "## Recent Tests",
            render_list_with_trust(latest_recent_tests(profile), ("name", "value", "unit", "flag", "date")),
            "",
            "## Follow Up",
            render_list_with_trust(profile.get("follow_up", []), ("task", "due_date", "status")),
            "",
            "## Preferences",
        ]
    )
    lines.extend(f"- {item}" for item in preferences_summary(profile))
    lines.extend(
        [
            "",
            "## Review Queue",
        ]
    )
    if open_review_items:
        lines.extend(
            f"- {item['id']} | {item['section']} | {render_record(item['candidate'], ('name', 'value', 'dose', 'task'))} "
            f"| {review_trust_label(item)} | source {item.get('source_title') or 'unknown'}"
            for item in open_review_items[:10]
        )
    else:
        lines.append("- none recorded")
    lines.extend(
        [
            "",
            "## Open Conflicts",
        ]
    )
    if open_conflict_items:
        lines.extend(
            f"- {item['section']} `{item['identity']}` field `{item['field']}`: "
            f"'{item['previous']}' vs '{item['new_value']}'"
            for item in open_conflict_items
        )
    else:
        lines.append("- none recorded")
    lines.append("")
    return "\n".join(lines)


def recent_note_summaries(root: Path, person_id: str, limit: int = 10) -> list[str]:
    directory = notes_dir(root, person_id)
    if not directory.exists():
        return []

    summaries = []
    for note_path in sorted(directory.glob("*.md"), reverse=True)[:limit]:
        lines = note_path.read_text(encoding="utf-8").strip().splitlines()
        title = lines[0].removeprefix("# ").strip() if lines else note_path.stem
        body = " ".join(line.strip() for line in lines[1:] if line.strip() and not line.startswith("- "))
        summaries.append(f"{title}: {body}".strip())
    return summaries


def parse_date_like(value: str) -> datetime | None:
    if not value:
        return None
    for parser in (
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def parse_numeric_value(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


TREND_THRESHOLDS = {
    "LDL": 10.0,
    "HDL": 5.0,
    "A1C": 0.3,
    "TSH": 0.5,
    "Weight": 2.0,
}


def render_trends_text(profile: dict[str, Any]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in profile.get("recent_tests", []):
        value = parse_numeric_value(item.get("value"))
        if value is None:
            continue
        name = normalize_test_name(str(item.get("name", "")))
        grouped.setdefault(name, []).append(item)

    lines = ["# Health Trends", ""]
    if not grouped:
        lines.append("No numeric lab trends available yet.")
        lines.append("")
        return "\n".join(lines)

    for name in sorted(grouped):
        series = sorted(grouped[name], key=lambda item: item.get("date", ""))
        latest = series[-1]
        latest_value = parse_numeric_value(latest.get("value"))
        earliest_value = parse_numeric_value(series[0].get("value"))
        change = ""
        significance = ""
        if latest_value is not None and earliest_value is not None and len(series) > 1:
            delta = latest_value - earliest_value
            change = f" | change {delta:+.2f}"
            threshold = TREND_THRESHOLDS.get(name, 0.0)
            if threshold and abs(delta) >= threshold:
                significance = " | notable trend"
        unit = latest.get("unit", "")
        unit_suffix = f" {unit}" if unit else ""
        lines.append(f"## {name}")
        lines.append(
            f"- Latest: {latest.get('value')}{unit_suffix} on {latest.get('date') or 'unknown'}"
            f"{change}{significance}"
        )
        if latest.get("reference_range"):
            lines.append(f"- Reference range: {latest.get('reference_range')}")
        if latest.get("flag"):
            lines.append(f"- Latest flag: {latest.get('flag')}")
        lines.append(
            "- Series: "
            + ", ".join(
                f"{item.get('date') or 'unknown'}={item.get('value')}{(' ' + item.get('unit')) if item.get('unit') else ''}"
                for item in series
            )
        )
        lines.append("")
    return "\n".join(lines)


def render_medication_reconciliation_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
) -> str:
    medication_reviews = [
        item for item in review_queue if item.get("section") == "medications" and item.get("status") == "open"
    ]
    medication_conflicts = [
        item for item in conflicts if item.get("section") == "medications" and item.get("status") == "open"
    ]

    lines = [
        "# Medication Reconciliation",
        "",
        "## Current Structured List",
        render_list(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
        "",
        "## Open Medication Conflicts",
    ]
    if medication_conflicts:
        lines.extend(
            f"- {item['identity']} field `{item['field']}`: '{item['previous']}' vs '{item['new_value']}'"
            for item in medication_conflicts
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Pending Medication Review Items"])
    if medication_reviews:
        lines.extend(
            f"- {item['id']}: {render_record(item['candidate'], ('name', 'dose', 'form', 'frequency', 'status'))} "
            f"| tier {item.get('tier')} | confidence {item.get('confidence')} | source {item.get('source_title')}"
            for item in medication_reviews
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Recent Medication History"])
    if medication_history:
        lines.extend(
            f"- {item['recorded_at']} | {item['event_type']} | {item['medication_name']}"
            for item in medication_history[-5:]
        )
    else:
        lines.append("- none recorded")
    lines.extend(
        [
            "",
            "## Next Actions",
            "- Confirm current medication names, doses, and frequency against the latest medication list or bottle photo.",
            "- Resolve any open medication conflicts before sharing this list with a clinician.",
            "",
        ]
    )
    return "\n".join(lines)


def escape_ics_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def render_calendar_ics(profile: dict[str, Any]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Health Skill//Follow Up Calendar//EN",
    ]
    for index, item in enumerate(profile.get("follow_up", []), start=1):
        due_date = item.get("due_date")
        task = item.get("task")
        if not due_date or not task:
            continue
        date_token = due_date.replace("-", "")
        uid = f"{profile.get('person_id', 'person')}-followup-{index}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART;VALUE=DATE:{date_token}",
                f"SUMMARY:{escape_ics_text(task)}",
                f"DESCRIPTION:{escape_ics_text('Generated from Health Skill follow-up list.')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    lines.append("")
    return "\n".join(lines)


def render_weight_trends_text(entries: list[dict[str, Any]]) -> str:
    lines = ["# Weight Trends", ""]
    if not entries:
        lines.append("No weight entries yet.")
        lines.append("")
        return "\n".join(lines)

    latest = entries[-1]
    lines.append(
        f"- Latest: {latest['value']} {latest['unit']} on {latest['entry_date']}"
    )
    if len(entries) > 1:
        delta = latest["value"] - entries[0]["value"]
        lines.append(
            f"- Change from first entry: {delta:+.2f} {latest['unit']}"
        )
    lines.append("")
    lines.append("## Series")
    lines.extend(
        f"- {item['entry_date']} | {item['value']} {item['unit']}"
        + (f" | {item['note']}" if item.get("note") else "")
        for item in entries
    )
    lines.append("")
    return "\n".join(lines)


def render_vitals_trends_text(entries: list[dict[str, Any]]) -> str:
    lines = ["# Vitals Trends", ""]
    if not entries:
        lines.append("No vital entries yet beyond weight tracking.")
        lines.append("")
        return "\n".join(lines)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        grouped.setdefault(item["metric"], []).append(item)

    for metric in sorted(grouped):
        lines.append(f"## {metric.replace('_', ' ').title()}")
        for item in grouped[metric][-10:]:
            unit = f" {item['unit']}" if item.get("unit") else ""
            note = f" | {item['note']}" if item.get("note") else ""
            lines.append(f"- {item['entry_date']} | {item['value_text']}{unit}{note}")
        lines.append("")
    return "\n".join(lines)


def latest_weight_summary(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "none recorded"
    latest = entries[-1]
    summary = f"{latest['value']} {latest['unit']} on {latest['entry_date']}"
    if len(entries) > 1:
        delta = latest["value"] - entries[0]["value"]
        summary += f" | change {delta:+.2f} {latest['unit']}"
    return summary


def build_timeline_events(
    root: Path,
    person_id: str,
    profile: dict[str, Any],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []

    for item in profile.get("encounters", []):
        events.append(
            {
                "date": item.get("date") or "",
                "kind": "encounter",
                "summary": render_record(item, ("date", "kind", "title", "summary")),
            }
        )
    for item in profile.get("follow_up", []):
        if item.get("due_date"):
            events.append(
                {
                    "date": item.get("due_date"),
                    "kind": "follow_up",
                    "summary": render_record(item, ("task", "due_date", "status")),
                }
            )
    for item in medication_history:
        events.append(
            {
                "date": item.get("recorded_at", ""),
                "kind": "medication",
                "summary": f"{item.get('event_type')} | {item.get('medication_name')}",
            }
        )
    for item in weight_entries:
        events.append(
            {
                "date": item.get("entry_date", ""),
                "kind": "weight",
                "summary": f"{item.get('value')} {item.get('unit')} | {item.get('note') or 'weight entry'}",
            }
        )
    for item in vital_entries:
        unit = f" {item.get('unit')}" if item.get("unit") else ""
        events.append(
            {
                "date": item.get("entry_date", ""),
                "kind": "vital",
                "summary": f"{item.get('metric')} | {item.get('value_text')}{unit} | {item.get('note') or 'vital entry'}",
            }
        )
    for note_path in sorted(notes_dir(root, person_id).glob("*.md")) if notes_dir(root, person_id).exists() else []:
        stem = note_path.stem
        note_date = stem.split("-", 3)[:3]
        if len(note_date) == 3:
            date_token = "-".join(note_date)
        else:
            date_token = ""
        title = note_path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ").strip()
        events.append(
            {
                "date": date_token,
                "kind": "note",
                "summary": title,
            }
        )

    events.sort(key=lambda item: (parse_date_like(item["date"]) or datetime.min.replace(tzinfo=timezone.utc), item["kind"]))
    return events


def render_timeline_text(events: list[dict[str, str]]) -> str:
    lines = ["# Health Timeline", ""]
    if not events:
        lines.append("No timeline events yet.")
        lines.append("")
        return "\n".join(lines)
    for event in events:
        lines.append(f"- {event['date'] or 'unknown'} | {event['kind']} | {event['summary']}")
    lines.append("")
    return "\n".join(lines)


def render_change_report_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
    days: int,
) -> str:
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400

    def is_recent(value: str) -> bool:
        parsed = parse_date_like(value)
        return bool(parsed and parsed.timestamp() >= cutoff)

    recent_reviews = [item for item in review_queue if is_recent(item.get("detected_at", ""))]
    recent_conflicts = [item for item in conflicts if is_recent(item.get("detected_at", ""))]
    recent_med_history = [item for item in medication_history if is_recent(item.get("recorded_at", ""))]
    recent_weights = [item for item in weight_entries if is_recent(item.get("entry_date", ""))]
    recent_vitals = [item for item in vital_entries if is_recent(item.get("entry_date", ""))]

    lines = [
        "# Health Change Report",
        "",
        f"Window: last {days} days",
        "",
        "## Review Queue Changes",
    ]
    if recent_reviews:
        lines.extend(
            f"- {item['id']} | {item['section']} | {item.get('tier')} | {item.get('source_title')}"
            for item in recent_reviews
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Conflict Changes"])
    if recent_conflicts:
        lines.extend(
            f"- {item['section']} `{item['identity']}` field `{item['field']}` changed"
            for item in recent_conflicts
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Medication Changes"])
    if recent_med_history:
        lines.extend(
            f"- {item['recorded_at']} | {item['event_type']} | {item['medication_name']}"
            for item in recent_med_history
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Weight Changes"])
    if recent_weights:
        lines.extend(
            f"- {item['entry_date']} | {item['value']} {item['unit']}"
            + (f" | {item['note']}" if item.get('note') else "")
            for item in recent_weights
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Other Vital Changes"])
    if recent_vitals:
        lines.extend(
            f"- {item['entry_date']} | {item['metric']} | {item['value_text']}"
            + (f" {item['unit']}" if item.get("unit") else "")
            + (f" | {item['note']}" if item.get("note") else "")
            for item in recent_vitals
        )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Current Abnormal Labs"])
    abnormal = [
        item
        for item in profile.get("recent_tests", [])
        if item.get("flag") in {"high", "low", "abnormal"}
    ]
    if abnormal:
        lines.extend(
            f"- {render_record(item, ('name', 'value', 'unit', 'flag', 'date'))}"
            for item in abnormal
        )
    else:
        lines.append("- none recorded")
    lines.append("")
    return "\n".join(lines)


def render_start_here_text(profile: dict[str, Any]) -> str:
    name = profile.get("name") or profile.get("person_id") or "this person"
    lines = [
        "# Start Here",
        "",
        f"This folder is the working health project for {name}. You do not need to open everything.",
        "",
        "## Best Order",
        "- Read HEALTH_HOME.md for the all-in-one view.",
        "- Read HEALTH_DOSSIER.md for the full current picture.",
        "- Read TODAY.md if you want the quickest next steps.",
        "- Read NEXT_APPOINTMENT.md before a visit or portal message.",
        "- Read REVIEW_WORKLIST.md when the system found new facts that still need confirmation.",
        "",
        "## When New Files Arrive",
        "- Drop them into inbox/.",
        "- Run process-inbox.",
        "- The originals will move into Archive/ after ingestion.",
        "",
        "## What This Workspace Optimizes For",
        "- less repetition across Claude sessions",
        "- cleaner appointment prep",
        "- clearer follow-up tracking",
        "- visible trust and conflicts instead of hidden assumptions",
        "",
    ]
    return "\n".join(lines)


def render_health_home_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
) -> str:
    next_item = next_follow_up(profile)
    lines = [
        "# Health Home",
        "",
        "This is the calmest place to start if you just want to know what matters now.",
        "",
        "## Right Now",
    ]
    lines.extend(f"- {item}" for item in current_priorities(profile, conflicts, inbox_files, review_queue))
    lines.extend(
        [
            "",
            "## Snapshot",
            f"- Person: {profile.get('name') or profile.get('person_id') or 'unknown'}",
            f"- Latest weight: {latest_weight_summary(weight_entries)}",
            f"- Next recorded follow-up: {render_record(next_item, ('task', 'due_date', 'status')) if next_item else 'none recorded'}",
            f"- Open review items: {len(open_reviews(review_queue))}",
            f"- Open conflicts: {len(open_conflicts_only(conflicts))}",
            "",
            "## Recent Signal",
        ]
    )
    abnormal = recent_abnormal_tests(profile, limit=3)
    if abnormal:
        lines.extend(
            f"- {item.get('name')} {item.get('value')} {item.get('unit', '')} | {item.get('flag') or 'flag not recorded'} | trust: {source_trust_label(item.get('source'))}"
            for item in abnormal
        )
    else:
        lines.append("- No abnormal lab flags are currently highlighted.")
    lines.extend(["", "## Progress"])
    lines.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    lines.extend(["", "## Metrics Being Tracked"])
    tracked = {"weight"} | {item["metric"] for item in vital_entries}
    lines.append("- " + ", ".join(sorted(metric.replace("_", " ") for metric in tracked if metric)))
    lines.append("")
    return "\n".join(lines)


def render_review_worklist_text(review_queue: list[dict[str, Any]]) -> str:
    open_items = open_reviews(review_queue)
    tier_groups = {
        "safe_to_auto_apply": [],
        "needs_quick_confirmation": [],
        "do_not_trust_without_human_review": [],
    }
    for item in open_items:
        tier_groups.setdefault(item.get("tier", "needs_quick_confirmation"), []).append(item)

    lines = [
        "# Review Worklist",
        "",
        "This file is meant to feel lighter than reading the raw JSON queue.",
        "",
        f"- Open review items: {len(open_items)}",
        "",
    ]
    if not open_items:
        lines.extend(
            [
                "## Good News",
                "- Nothing is waiting for review right now.",
                "",
            ]
        )
        return "\n".join(lines)

    labels = {
        "safe_to_auto_apply": "Probably Safe To Accept",
        "needs_quick_confirmation": "Quick Confirmation Recommended",
        "do_not_trust_without_human_review": "Needs Careful Human Review",
    }
    for tier in ("safe_to_auto_apply", "needs_quick_confirmation", "do_not_trust_without_human_review"):
        lines.append(f"## {labels[tier]}")
        if tier_groups.get(tier):
            for item in tier_groups[tier]:
                lines.append(
                    f"- {item['id']} | {item['section']} | "
                    f"{render_record(item['candidate'], ('name', 'value', 'dose', 'task'))} | "
                    f"{review_trust_label(item)} | source {item.get('source_title') or 'unknown'}"
                )
                if item.get("applied"):
                    lines.append("  Added to the structured record already, but still worth a quick glance.")
                snippet = review_source_snippet(item)
                if snippet:
                    lines.append(f"  Evidence: {snippet}")
        else:
            lines.append("- none recorded")
        lines.append("")
    lines.extend(
        [
            "## Suggested Flow",
            "- Accept the safe items first.",
            "- Quick-check the medium-confidence items against the source document.",
            "- Leave low-trust OCR or ambiguous items unresolved until a human confirms them.",
            "",
        ]
    )
    return "\n".join(lines)


def thirty_second_summary(profile: dict[str, Any], conflicts: list[dict[str, Any]], review_queue: list[dict[str, Any]]) -> str:
    parts = []
    if profile.get("conditions"):
        parts.append(
            "known conditions: " + ", ".join(item.get("name", "unknown") for item in profile["conditions"][:3] if item.get("name"))
        )
    if profile.get("medications"):
        parts.append(
            "current meds: " + ", ".join(item.get("name", "unknown") for item in profile["medications"][:3] if item.get("name"))
        )
    if recent_abnormal_tests(profile, limit=2):
        abnormal = ", ".join(
            f"{item.get('name')} {item.get('value')} {item.get('unit', '')}".strip()
            for item in recent_abnormal_tests(profile, limit=2)
        )
        parts.append(f"recent abnormal labs: {abnormal}")
    next_item = next_follow_up(profile)
    if next_item:
        parts.append(f"next follow-up: {next_item.get('task')} by {next_item.get('due_date') or 'unknown'}")
    if open_conflicts_only(conflicts):
        parts.append(f"{len(open_conflicts_only(conflicts))} open source conflict(s)")
    if open_reviews(review_queue):
        parts.append(f"{len(open_reviews(review_queue))} extracted item(s) still need review")
    return "; ".join(parts) if parts else "No major open health workspace issues are recorded right now."


def suggested_visit_questions(profile: dict[str, Any]) -> list[str]:
    questions = []
    for item in recent_abnormal_tests(profile, limit=2):
        questions.append(
            f"What does the recent {item.get('name')} result of {item.get('value')} {item.get('unit', '')} mean in context?"
        )
    for item in pending_follow_ups(profile)[:2]:
        task = item.get("task")
        if task:
            questions.append(f"What should we do next about: {task}?")
    for item in profile.get("unresolved_questions", [])[:2]:
        text = item.get("text")
        if text:
            questions.append(text)
    if not questions:
        questions = [
            "What matters most for this visit?",
            "What should we monitor before the next follow-up?",
            "What should prompt a sooner message or visit?",
        ]
    return questions[:5]


def render_today_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
) -> str:
    due_now = due_follow_ups(profile, days=0)
    lines = [
        "# Today",
        "",
        "You do not need to solve everything today. Focus on the smallest set of actions that keeps the record reliable and the next step clear.",
        "",
        "## Focus Now",
    ]
    lines.extend(f"- {item}" for item in current_priorities(profile, conflicts, inbox_files, review_queue))
    lines.extend(["", "## Actionable Today"])
    actionable = []
    if inbox_files:
        actionable.append(f"Process inbox to handle {len(inbox_files)} waiting file(s).")
    if due_now:
        actionable.extend(
            f"Follow up on: {item.get('task')} ({item.get('due_date') or 'no date'})"
            for item in due_now[:5]
        )
    if open_reviews(review_queue):
        actionable.append(f"Review {len(open_reviews(review_queue))} extracted item(s).")
    if open_conflicts_only(conflicts):
        actionable.append(f"Resolve {len(open_conflicts_only(conflicts))} source conflict(s).")
    if not actionable:
        actionable.append("No urgent workspace maintenance is needed today.")
    lines.extend(f"- {item}" for item in actionable)
    lines.extend(["", "## Quick Reassurance"])
    lines.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    lines.append("")
    return "\n".join(lines)


def render_this_week_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
) -> str:
    due_soon = due_follow_ups(profile, days=7)
    lines = [
        "# This Week",
        "",
        "This view is for planning, not panic. It pulls forward what is due soon so the next appointment or task does not sneak up on you.",
        "",
        "## Coming Up",
    ]
    if due_soon:
        lines.extend(
            f"- {item.get('task')} | due {item.get('due_date') or 'unknown'} | status {item.get('status') or 'unknown'}"
            for item in due_soon[:10]
        )
    else:
        lines.append("- No dated follow-ups are due within 7 days.")
    lines.extend(["", "## Work To Clear"])
    cleanup = []
    if inbox_files:
        cleanup.append(f"{len(inbox_files)} inbox file(s) still need processing.")
    if open_reviews(review_queue):
        cleanup.append(f"{len(open_reviews(review_queue))} review item(s) still need confirmation.")
    if open_conflicts_only(conflicts):
        cleanup.append(f"{len(open_conflicts_only(conflicts))} conflict(s) still need resolution.")
    if not cleanup:
        cleanup.append("No record-cleanup tasks are piling up.")
    lines.extend(f"- {item}" for item in cleanup)
    lines.extend(["", "## Good Momentum"])
    lines.append(f"- Completed follow-ups on record: {completed_follow_up_count(profile)}")
    lines.append("")
    return "\n".join(lines)


def render_next_appointment_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
) -> str:
    next_item = next_follow_up(profile)
    lines = [
        "# Next Appointment",
        "",
        "Use this before a visit, telehealth message, or provider-portal note.",
        "",
        "## At A Glance",
        f"- Patient: {profile.get('name') or profile.get('person_id') or 'unknown'}",
        f"- Next follow-up on record: {render_record(next_item, ('task', 'due_date', 'status')) if next_item else 'none recorded'}",
        "",
        "## 30-Second Summary",
        f"- {thirty_second_summary(profile, conflicts, review_queue)}",
        "",
        "## Short Portal Message Draft",
        f"- Hello, I am following up about {next_item.get('task') if next_item else 'the next visit'}. "
        f"The main recent changes are: {thirty_second_summary(profile, conflicts, review_queue)}",
        "",
        "## Current Medications",
        render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
        "",
        "## Most Relevant Recent Tests",
        render_list_with_trust(latest_recent_tests(profile, limit=5), ("name", "value", "unit", "flag", "date")),
        "",
        "## What To Bring Up In Plain Language",
    ]
    talking_points = []
    if recent_abnormal_tests(profile, limit=3):
        talking_points.extend(
            f"Ask how to interpret the recent {item.get('name')} result."
            for item in recent_abnormal_tests(profile, limit=2)
        )
    if pending_follow_ups(profile):
        talking_points.extend(
            f"Confirm the next step for: {item.get('task')}"
            for item in pending_follow_ups(profile)[:2]
            if item.get("task")
        )
    if not talking_points:
        talking_points.append("Explain the main concern and ask what should be monitored next.")
    lines.extend(f"- {item}" for item in talking_points[:4])
    lines.extend([
        "",
        "## What Changed Recently",
    ])
    recent_changes = []
    if recent_abnormal_tests(profile, limit=3):
        recent_changes.append(
            "Recent abnormal labs: "
            + ", ".join(
                f"{item.get('name')} {item.get('value')} {item.get('unit', '')}".strip()
                for item in recent_abnormal_tests(profile, limit=3)
            )
        )
    if open_reviews(review_queue):
        recent_changes.append(f"{len(open_reviews(review_queue))} extracted item(s) still need confirmation.")
    if open_conflicts_only(conflicts):
        recent_changes.append(f"{len(open_conflicts_only(conflicts))} source conflict(s) remain open.")
    if not recent_changes:
        recent_changes.append("No major recent record changes are flagged.")
    lines.extend(f"- {item}" for item in recent_changes)
    lines.extend(["", "## Best Questions To Ask"])
    lines.extend(f"- {item}" for item in suggested_visit_questions(profile))
    lines.append("")
    return "\n".join(lines)


def render_care_status_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
) -> str:
    lines = [
        "# Care Status",
        "",
        "This is the quick progress board for the project.",
        "",
        "## Signals",
    ]
    lines.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    lines.extend(
        [
            "",
            "## Next Wins",
            f"- {current_priorities(profile, conflicts, inbox_files, review_queue)[0]}",
            "",
        ]
    )
    return "\n".join(lines)


def render_intake_summary_text(
    processed_files: list[tuple[Path, Path]],
    new_review_items: list[dict[str, Any]],
) -> str:
    lines = [
        "# Intake Summary",
        "",
        "This is the plain-language report for the latest inbox pass.",
        "",
        f"- Files processed: {len(processed_files)}",
        f"- Possible updates found: {len(new_review_items)}",
        "",
    ]
    if processed_files:
        lines.extend(
            [
                "## What Happened",
                f"- I processed {len(processed_files)} file(s) from inbox/ and moved the originals into Archive/.",
            ]
        )
        if new_review_items:
            safe = sum(1 for item in new_review_items if item.get("tier") == "safe_to_auto_apply")
            quick = sum(1 for item in new_review_items if item.get("tier") == "needs_quick_confirmation")
            cautious = sum(
                1 for item in new_review_items if item.get("tier") == "do_not_trust_without_human_review"
            )
            lines.extend(
                [
                    f"- I found {len(new_review_items)} likely updates.",
                    f"- {safe} looked safe enough to add with low friction.",
                    f"- {quick} need a quick confirmation.",
                    f"- {cautious} should not be trusted without a human check.",
                    "",
                    "## New Review Items",
                ]
            )
            for item in new_review_items[:12]:
                lines.append(
                    f"- {item['id']} | {item['section']} | {render_record(item['candidate'], ('name', 'value', 'dose', 'task'))} "
                    f"| {review_trust_label(item)}"
                )
        else:
            lines.extend(
                [
                    "- I did not find any structured updates worth adding right away.",
                ]
            )
    else:
        lines.extend(
            [
                "## Nothing New",
                "- Inbox was empty, so there was nothing to process.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def render_assistant_update_text(title: str, bullets: list[str]) -> str:
    lines = [
        "# Assistant Update",
        "",
        title,
        "",
    ]
    lines.extend(f"- {item}" for item in bullets)
    lines.append("")
    return "\n".join(lines)


def render_appointment_request_text(
    profile: dict[str, Any],
    specialty: str,
    reason: str,
    visit_type: str,
) -> str:
    return "\n".join(
        [
            "# Appointment Request",
            "",
            f"- Patient: {profile.get('name') or profile.get('person_id')}",
            f"- Specialty: {specialty}",
            f"- Visit type: {visit_type}",
            f"- Reason: {reason}",
            "",
            "## Current Medications",
            render_list(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
            "",
            "## Relevant Conditions",
            render_list(profile.get("conditions", []), ("name", "status")),
            "",
            "## Recent Tests",
            render_list(profile.get("recent_tests", []), ("name", "value", "date")),
            "",
            "## Scheduling Notes",
            "- Generated for use in a calendar tool, booking form, or provider portal message.",
            "",
        ]
    )


def redacted_identifier(profile: dict[str, Any]) -> str:
    name = str(profile.get("name") or "").strip()
    if not name:
        return profile.get("person_id") or "patient"
    parts = [part[0].upper() for part in name.split() if part]
    return "".join(parts[:3]) or "patient"


def render_redacted_summary_text(profile: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Redacted Health Summary",
            "",
            f"- Patient reference: {redacted_identifier(profile)}",
            f"- Known conditions: {', '.join(item.get('name', 'unknown') for item in profile.get('conditions', [])[:5]) or 'none recorded'}",
            f"- Current medications: {', '.join(item.get('name', 'unknown') for item in profile.get('medications', [])[:8]) or 'none recorded'}",
            f"- Allergies: {', '.join(item.get('substance', 'unknown') for item in profile.get('allergies', [])[:8]) or 'none recorded'}",
            "",
            "## Recent Tests",
            render_list_with_trust(latest_recent_tests(profile, limit=5), ("name", "value", "unit", "flag", "date")),
            "",
            "## Follow Up",
            render_list_with_trust(profile.get("follow_up", []), ("task", "due_date", "status")),
            "",
        ]
    )


def render_clinician_packet_text(profile: dict[str, Any], visit_type: str, reason: str) -> str:
    return "\n".join(
        [
            "# Clinician Packet",
            "",
            f"- Patient: {profile.get('name') or profile.get('person_id') or 'unknown'}",
            f"- Visit type: {visit_type}",
            f"- Main reason: {reason}",
            "",
            "## 30-Second Summary",
            f"- {thirty_second_summary(profile, [], [])}",
            "",
            "## Conditions",
            render_list_with_trust(profile.get("conditions", []), ("name", "status")),
            "",
            "## Current Medications",
            render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
            "",
            "## Allergies",
            render_list_with_trust(profile.get("allergies", []), ("substance", "reaction", "severity")),
            "",
            "## Recent Tests",
            render_list_with_trust(latest_recent_tests(profile, limit=6), ("name", "value", "unit", "flag", "date")),
            "",
            "## Follow Up And Questions",
            render_list_with_trust(profile.get("follow_up", []), ("task", "due_date", "status")),
            "",
            "## Questions To Discuss",
            "\n".join(f"- {item}" for item in suggested_visit_questions(profile)),
            "",
        ]
    )


def render_portal_message_text(profile: dict[str, Any], message_goal: str) -> str:
    summary = thirty_second_summary(profile, [], [])
    return "\n".join(
        [
            "# Portal Message Draft",
            "",
            f"Hello, I am reaching out about {message_goal}.",
            "",
            f"Short summary: {summary}.",
            "",
            "Questions:",
            *(f"- {item}" for item in suggested_visit_questions(profile)[:3]),
            "",
            "Thank you.",
            "",
        ]
    )


def create_backup_archive(root: Path, person_id: str) -> Path:
    target_dir = exports_dir(root, person_id)
    archive_name = f"health-backup-{date.today().isoformat()}.zip"
    with tempfile.TemporaryDirectory() as temp_dir:
        archive_base = Path(temp_dir) / f"health-backup-{date.today().isoformat()}"
        archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=person_dir(root, person_id))
        final_path = target_dir / archive_name
        shutil.move(archive_path, final_path)
    return final_path


def render_dossier_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    notes: list[str],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
) -> str:
    open_conflict_items = open_conflicts_only(conflicts)
    open_review_items = open_reviews(review_queue)
    priorities = current_priorities(profile, conflicts, inbox_files, review_queue)
    sections = [
        "# Health Dossier",
        "",
        "## Identity",
        f"- Name: {profile.get('name') or 'unknown'}",
        f"- Person ID: `{profile.get('person_id') or 'unknown'}`",
        f"- Date of birth: {profile.get('date_of_birth') or 'unknown'}",
        f"- Sex: {profile.get('sex') or 'unknown'}",
        f"- Last updated: {profile.get('audit', {}).get('updated_at') or 'unknown'}",
        f"- Latest weight: {latest_weight_summary(weight_entries)}",
        "",
        "## Snapshot",
        "This file is the canonical project-level context for Claude. Start here, then open only the notes or documents needed for the task at hand.",
        f"Pending inbox files: {len(inbox_files)}",
        "",
        "## Current Priorities",
    ]
    sections.extend(f"- {item}" for item in priorities)
    sections.extend(
        [
            "",
            "## Person Preferences",
        ]
    )
    sections.extend(f"- {item}" for item in preferences_summary(profile))
    sections.extend(
        [
            "",
        "## Known Conditions",
        render_list_with_trust(profile.get("conditions", []), ("name", "status")),
        "",
        "## Current Medications",
        render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
        "",
        "## Allergies",
        render_list_with_trust(profile.get("allergies", []), ("substance", "reaction", "severity")),
        "",
        "## Clinicians",
        render_list_with_trust(profile.get("clinicians", []), ("name", "role", "contact")),
        "",
        "## Recent Tests",
        render_list_with_trust(
            latest_recent_tests(profile, limit=10),
            ("name", "value", "unit", "flag", "date", "reference_range"),
        ),
        "",
        "## Follow Up",
        render_list_with_trust(profile.get("follow_up", []), ("task", "due_date", "status")),
        "",
        "## Weight",
        f"- {latest_weight_summary(weight_entries)}",
        "",
        "## Unresolved Questions",
        render_list_with_trust(profile.get("unresolved_questions", []), ("text",)),
        "",
        "## Document Index",
        render_list_with_trust(profile.get("documents", []), ("title", "doc_type", "source_date", "review_required")),
        "",
        "## Encounter Timeline",
        render_list_with_trust(profile.get("encounters", []), ("date", "kind", "title", "summary")),
        "",
        "## Recent Notes",
        ]
    )
    if notes:
        sections.extend(f"- {item}" for item in notes)
    else:
        sections.append("- none recorded")
    sections.extend(
        [
            "",
        "## Inbox",
        ]
    )
    if inbox_files:
        sections.extend(f"- {path.name}" for path in inbox_files)
    else:
        sections.append("- inbox empty")
    sections.extend(
        [
            "",
            "## Review Queue",
        ]
    )
    if open_review_items:
        sections.extend(
            f"- {item['id']} | {item['section']} | {render_record(item['candidate'], ('name', 'value', 'dose', 'task'))} "
            f"| {review_trust_label(item)} | source {item.get('source_title') or 'unknown'}"
            for item in open_review_items[:20]
        )
    else:
        sections.append("- none recorded")
    sections.extend(
        [
            "",
            "## Open Conflicts",
        ]
    )
    if open_conflict_items:
        sections.extend(
            f"- {item['section']} `{item['identity']}` field `{item['field']}`: "
            f"'{item['previous']}' vs '{item['new_value']}'"
            for item in open_conflict_items
        )
    else:
        sections.append("- none recorded")
    sections.extend(
        [
            "",
            "## Confidence And Progress",
        ]
    )
    sections.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    sections.extend(
        [
            "",
            "## Working Rules For Claude",
            "- Read this file first, then check TODAY.md or NEXT_APPOINTMENT.md before opening raw documents.",
            "- Treat clinician-authored diagnoses and plans as higher confidence than user recollection unless the user says otherwise.",
            "- Keep trust visible. Say whether a fact is clinician-confirmed, user-reported, or still awaiting review.",
            "- Do not overwrite stable facts silently when a new source disagrees. Keep the latest value, record the conflict, and surface it here.",
            "- Prefer updating structured fields first, then regenerate this dossier and the day-to-day views.",
            "- Do not write speculative diagnoses into the structured record.",
            "",
        ]
    )
    return "\n".join(sections)


def refresh_views(root: Path, person_id: str) -> tuple[Path, Path]:
    profile = load_profile(root, person_id)
    conflicts = load_conflicts(root, person_id)
    review_queue = load_review_queue(root, person_id)
    medication_history = load_medication_history(root, person_id)
    weight_entries = load_weight_entries(root, person_id)
    vital_entries = load_vital_entries(root, person_id)
    inbox_files = list_inbox_files(root, person_id)
    sync_conflict_count(root, person_id, profile)
    sync_review_count(root, person_id, profile)
    save_profile(root, person_id, profile)

    summary = render_summary_text(profile, conflicts, inbox_files, review_queue, weight_entries)
    atomic_write_text(summary_path(root, person_id), summary)
    atomic_write_text(
        home_path(root, person_id),
        render_health_home_text(profile, conflicts, inbox_files, review_queue, weight_entries, vital_entries),
    )
    atomic_write_text(start_here_path(root, person_id), render_start_here_text(profile))
    atomic_write_text(
        today_path(root, person_id),
        render_today_text(profile, conflicts, inbox_files, review_queue),
    )
    atomic_write_text(
        this_week_path(root, person_id),
        render_this_week_text(profile, conflicts, inbox_files, review_queue),
    )
    atomic_write_text(
        next_appointment_path(root, person_id),
        render_next_appointment_text(profile, conflicts, review_queue),
    )
    atomic_write_text(
        review_worklist_path(root, person_id),
        render_review_worklist_text(review_queue),
    )
    atomic_write_text(
        care_status_path(root, person_id),
        render_care_status_text(profile, conflicts, inbox_files, review_queue),
    )

    dossier = render_dossier_text(
        profile,
        conflicts,
        recent_note_summaries(root, person_id),
        inbox_files,
        review_queue,
        weight_entries,
    )
    atomic_write_text(dossier_path(root, person_id), dossier)
    atomic_write_text(trends_path(root, person_id), render_trends_text(profile))
    atomic_write_text(weight_trends_path(root, person_id), render_weight_trends_text(weight_entries))
    atomic_write_text(vitals_trends_path(root, person_id), render_vitals_trends_text(vital_entries))
    atomic_write_text(
        timeline_path(root, person_id),
        render_timeline_text(
            build_timeline_events(root, person_id, profile, medication_history, weight_entries, vital_entries)
        ),
    )
    atomic_write_text(
        change_report_path(root, person_id),
        render_change_report_text(
            profile,
            conflicts,
            review_queue,
            medication_history,
            weight_entries,
            vital_entries,
            30,
        ),
    )
    atomic_write_text(
        reconciliation_path(root, person_id),
        render_medication_reconciliation_text(profile, conflicts, review_queue, medication_history),
    )

    return summary_path(root, person_id), dossier_path(root, person_id)


def command_init_project(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, ""):
        directory = ensure_person(
            root,
            "",
            args.name,
            args.date_of_birth,
            args.sex,
        )
        summary, dossier = refresh_views(root, "")
        write_assistant_update(
            root,
            "",
            "I initialized the Health Skill workspace.",
            [
                "The project folder now has the core structured files.",
                "HEALTH_HOME.md and TODAY.md are ready as the main starting points.",
                "You can drop new files into inbox/ whenever you want me to ingest them.",
            ],
        )
    print(directory)
    print(summary)
    print(dossier)
    return 0


def command_create_person(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        directory = ensure_person(
            root,
            args.person_id,
            args.name,
            args.date_of_birth,
            args.sex,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            f"I created the workspace for {args.name or args.person_id}.",
            [
                "The main project files are in place.",
                "The record is ready for inbox processing, notes, and appointment prep.",
            ],
        )
    print(directory)
    return 0


def command_update_profile(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        set_nested_field(profile, args.field, parse_value(args.value))
        sync_conflict_count(root, args.person_id, profile)
        path = save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I updated the profile.",
            [
                f"Field updated: {args.field}.",
                "I refreshed the user-facing views so the change is visible everywhere.",
            ],
        )
    print(path)
    return 0


def command_upsert_record(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path, _ = upsert_record(
            root,
            args.person_id,
            args.section,
            parse_value(args.value),
            args.source_type,
            args.source_label,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            f"I updated the {args.section} record.",
            [
                "The structured profile was refreshed.",
                "The dossier and day-to-day views were regenerated.",
            ],
        )
    print(path)
    return 0


def command_add_note(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        note_path = add_note(
            root,
            args.person_id,
            args.title,
            args.body,
            args.source_type,
            args.source_label,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I added a dated note.",
            [
                f"Note title: {args.title}.",
                "The timeline and current views were refreshed.",
            ],
        )
    print(note_path)
    return 0


def command_ingest_document(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        destination_path, note_path = ingest_document(
            root,
            args.person_id,
            Path(args.path),
            args.doc_type,
            args.title,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I ingested a document into the workspace.",
            [
                f"Archived file: {destination_path.name}.",
                "The structured record and review queue were refreshed.",
                "Any extracted facts were logged with visible trust labels.",
            ],
        )
    print(destination_path)
    print(note_path)
    return 0


def command_process_inbox(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        before_ids = {item["id"] for item in load_review_queue(root, args.person_id)}
        processed = process_inbox(root, args.person_id)
        refresh_views(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        new_review_items = [item for item in review_queue if item["id"] not in before_ids]
        atomic_write_text(
            intake_summary_path(root, args.person_id),
            render_intake_summary_text(processed, new_review_items),
        )
        write_assistant_update(
            root,
            args.person_id,
            "I finished processing the inbox.",
            [
                f"Files processed: {len(processed)}.",
                f"Possible updates found: {len(new_review_items)}.",
                "The originals were moved into Archive/ and the workspace views were refreshed.",
            ],
        )
    for archived_path, note_path in processed:
        print(archived_path)
        print(note_path)
    print(intake_summary_path(root, args.person_id))
    return 0


def command_list_review_queue(args: argparse.Namespace) -> int:
    items = load_review_queue(Path(args.root), args.person_id)
    if args.status:
        items = [item for item in items if item.get("status") == args.status]
    print(json.dumps(items, indent=2))
    return 0


def command_resolve_review_item(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        updated = False
        for item in items:
            if item["id"] == args.review_id:
                item["status"] = args.status
                item["resolution_note"] = args.note or ""
                item["resolved_at"] = now_utc()
                updated = True
                break
        if not updated:
            raise SystemExit(f"Review item not found: {args.review_id}")
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I resolved a review item.",
            [
                f"Review item: {args.review_id}.",
                f"Decision: {args.status}.",
            ],
        )
    print(review_queue_path(root, args.person_id))
    return 0


def command_apply_review_item(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        target = None
        for item in items:
            if item["id"] == args.review_id:
                target = item
                break
        if target is None:
            raise SystemExit(f"Review item not found: {args.review_id}")
        upsert_record(
            root,
            args.person_id,
            target["section"],
            target["candidate"],
            source_type="review-application",
            source_label=target.get("source_title", ""),
            source_date=target.get("source_date", ""),
        )
        target["applied"] = True
        target["status"] = "applied"
        target["applied_at"] = now_utc()
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I applied a reviewed item into the structured record.",
            [
                f"Review item: {args.review_id}.",
                "The dossier and quick views now reflect that accepted fact.",
            ],
        )
    print(review_queue_path(root, args.person_id))
    return 0


def command_apply_review_tier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        changed = 0
        for item in items:
            if item.get("status") != "open" or item.get("tier") != args.tier or item.get("applied"):
                continue
            upsert_record(
                root,
                args.person_id,
                item["section"],
                item["candidate"],
                source_type="review-application",
                source_label=item.get("source_title", ""),
                source_date=item.get("source_date", ""),
            )
            item["applied"] = True
            item["status"] = "applied"
            item["applied_at"] = now_utc()
            changed += 1
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I batch-applied review items.",
            [
                f"Tier: {args.tier}.",
                f"Items applied: {changed}.",
            ],
        )
    print(f"Applied {changed} review items")
    return 0


def command_resolve_review_tier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        changed = 0
        for item in items:
            if item.get("status") != "open" or item.get("tier") != args.tier:
                continue
            item["status"] = args.status
            item["resolution_note"] = args.note or ""
            item["resolved_at"] = now_utc()
            changed += 1
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I batch-resolved review items.",
            [
                f"Tier: {args.tier}.",
                f"Decision: {args.status}.",
                f"Items resolved: {changed}.",
            ],
        )
    print(f"Resolved {changed} review items")
    return 0


def command_render_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path, _ = refresh_views(root, args.person_id)
    print(path)
    return 0


def command_render_dossier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        _, path = refresh_views(root, args.person_id)
    print(path)
    return 0


def command_render_home(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(home_path(root, args.person_id))
    return 0


def command_render_today(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(today_path(root, args.person_id))
    return 0


def command_render_this_week(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(this_week_path(root, args.person_id))
    return 0


def command_render_next_appointment(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(next_appointment_path(root, args.person_id))
    return 0


def command_render_review_worklist(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(review_worklist_path(root, args.person_id))
    return 0


def command_render_care_status(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(care_status_path(root, args.person_id))
    return 0


def command_render_intake_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        if not intake_summary_path(root, args.person_id).exists():
            atomic_write_text(
                intake_summary_path(root, args.person_id),
                render_intake_summary_text([], []),
            )
    print(intake_summary_path(root, args.person_id))
    return 0


def command_render_timeline(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        weight_entries = load_weight_entries(root, args.person_id)
        vital_entries = load_vital_entries(root, args.person_id)
        atomic_write_text(
            timeline_path(root, args.person_id),
            render_timeline_text(
                build_timeline_events(root, args.person_id, profile, medication_history, weight_entries, vital_entries)
            ),
        )
    print(timeline_path(root, args.person_id))
    return 0


def command_render_change_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        conflicts = load_conflicts(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        weight_entries = load_weight_entries(root, args.person_id)
        vital_entries = load_vital_entries(root, args.person_id)
        atomic_write_text(
            change_report_path(root, args.person_id),
            render_change_report_text(
                profile,
                conflicts,
                review_queue,
                medication_history,
                weight_entries,
                vital_entries,
                args.days,
            ),
        )
    print(change_report_path(root, args.person_id))
    return 0


def command_render_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        atomic_write_text(trends_path(root, args.person_id), render_trends_text(profile))
    print(trends_path(root, args.person_id))
    return 0


def command_record_weight(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entry_date = args.date or date.today().isoformat()
        record_weight(root, args.person_id, entry_date, args.value, args.unit, args.note)
        record_vital(root, args.person_id, entry_date, "weight", str(args.value), args.unit, args.note)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I recorded a new weight entry.",
            [
                f"Entry: {args.value} {args.unit} on {entry_date}.",
                "Weight and vital trend views were refreshed.",
            ],
        )
    print(metrics_db_path(root, args.person_id))
    return 0


def command_record_vital(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entry_date = args.date or date.today().isoformat()
        record_vital(root, args.person_id, entry_date, args.metric, args.value, args.unit, args.note)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I recorded a non-weight health metric.",
            [
                f"Metric: {args.metric}.",
                f"Value: {args.value}{(' ' + args.unit) if args.unit else ''}.",
                "The vitals trend view was refreshed.",
            ],
        )
    print(metrics_db_path(root, args.person_id))
    return 0


def command_render_weight_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entries = load_weight_entries(root, args.person_id)
        atomic_write_text(weight_trends_path(root, args.person_id), render_weight_trends_text(entries))
        refresh_views(root, args.person_id)
    print(weight_trends_path(root, args.person_id))
    return 0


def command_render_vitals_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entries = load_vital_entries(root, args.person_id)
        atomic_write_text(vitals_trends_path(root, args.person_id), render_vitals_trends_text(entries))
        refresh_views(root, args.person_id)
    print(vitals_trends_path(root, args.person_id))
    return 0


def command_reconcile_medications(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        conflicts = load_conflicts(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        atomic_write_text(
            reconciliation_path(root, args.person_id),
            render_medication_reconciliation_text(profile, conflicts, review_queue, medication_history),
        )
    print(reconciliation_path(root, args.person_id))
    return 0


def command_export_calendar(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        atomic_write_text(calendar_export_path(root, args.person_id), render_calendar_ics(profile))
    print(calendar_export_path(root, args.person_id))
    return 0


def command_export_redacted_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / "redacted_summary.md"
        atomic_write_text(path, render_redacted_summary_text(profile))
        write_assistant_update(
            root,
            args.person_id,
            "I created a redacted shareable summary.",
            [
                "Direct identifiers were reduced.",
                "The export keeps only the essentials for sharing.",
            ],
        )
    print(path)
    return 0


def command_export_clinician_packet(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / f"clinician_packet_{slugify(args.visit_type)}.md"
        atomic_write_text(path, render_clinician_packet_text(profile, args.visit_type, args.reason))
        write_assistant_update(
            root,
            args.person_id,
            "I created a clinician packet.",
            [
                f"Visit type: {args.visit_type}.",
                "It keeps the focus on what a clinician is most likely to need quickly.",
            ],
        )
    print(path)
    return 0


def command_export_portal_message(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / "portal_message_draft.md"
        atomic_write_text(path, render_portal_message_text(profile, args.goal))
        write_assistant_update(
            root,
            args.person_id,
            "I drafted a short portal message.",
            [
                "The message is based on the current record and recent changes.",
                "It is ready to edit before sending.",
            ],
        )
    print(path)
    return 0


def command_generate_appointment_request(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        filename = f"appointment_request_{slugify(args.specialty)}.md"
        path = exports_dir(root, args.person_id) / filename
        atomic_write_text(
            path,
            render_appointment_request_text(
                profile,
                args.specialty,
                args.reason,
                args.visit_type,
            ),
        )
        write_assistant_update(
            root,
            args.person_id,
            "I created an appointment request draft.",
            [
                f"Specialty: {args.specialty}.",
                "This draft is ready for a booking form or provider portal.",
            ],
        )
    print(path)
    return 0


def command_list_conflicts(args: argparse.Namespace) -> int:
    conflicts = load_conflicts(Path(args.root), args.person_id)
    if args.status:
        conflicts = [item for item in conflicts if item["status"] == args.status]
    print(json.dumps(conflicts, indent=2))
    return 0


def command_resolve_conflict(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        conflicts = load_conflicts(root, args.person_id)
        updated = False
        for item in conflicts:
            if item["id"] == args.conflict_id:
                item["status"] = "resolved"
                item["resolution"] = args.resolution
                item["resolution_note"] = args.note or ""
                item["resolved_at"] = now_utc()
                updated = True
                break
        if not updated:
            raise SystemExit(f"Conflict not found: {args.conflict_id}")
        save_conflicts(root, args.person_id, conflicts)
        profile = load_profile(root, args.person_id)
        sync_conflict_count(root, args.person_id, profile)
        save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I resolved a source conflict.",
            [
                f"Conflict: {args.conflict_id}.",
                f"Resolution: {args.resolution}.",
            ],
        )
    print(conflicts_path(root, args.person_id))
    return 0


def command_set_preference(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        preferences = profile.setdefault("preferences", deepcopy(DEFAULT_PROFILE["preferences"]))
        preferences[args.key] = parse_value(args.value)
        save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I updated a workspace preference.",
            [
                f"Preference: {args.key}.",
                "The user-facing files now reflect that preference.",
            ],
        )
    print(profile_path(root, args.person_id))
    return 0


def command_backup_project(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path = create_backup_archive(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I created a workspace backup archive.",
            [
                f"Backup file: {path.name}.",
                "This is useful before major edits or when you want a portable copy.",
            ],
        )
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Health Skill workspace helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = subparsers.add_parser("init-project")
    init_project.add_argument("--root", required=True)
    init_project.add_argument("--name", default="")
    init_project.add_argument("--date-of-birth", default="")
    init_project.add_argument("--sex", default="")
    init_project.set_defaults(func=command_init_project)

    create_person = subparsers.add_parser("create-person")
    create_person.add_argument("--root", required=True)
    create_person.add_argument("--person-id", required=True)
    create_person.add_argument("--name", default="")
    create_person.add_argument("--date-of-birth", default="")
    create_person.add_argument("--sex", default="")
    create_person.set_defaults(func=command_create_person)

    update_profile = subparsers.add_parser("update-profile")
    update_profile.add_argument("--root", required=True)
    update_profile.add_argument("--person-id", default="")
    update_profile.add_argument("--field", required=True)
    update_profile.add_argument("--value", required=True)
    update_profile.set_defaults(func=command_update_profile)

    upsert = subparsers.add_parser("upsert-record")
    upsert.add_argument("--root", required=True)
    upsert.add_argument("--person-id", default="")
    upsert.add_argument("--section", choices=sorted(RECORD_KEYS), required=True)
    upsert.add_argument("--value", required=True)
    upsert.add_argument("--source-type", default="user")
    upsert.add_argument("--source-label", default="")
    upsert.add_argument("--source-date", default="")
    upsert.set_defaults(func=command_upsert_record)

    add_note_parser = subparsers.add_parser("add-note")
    add_note_parser.add_argument("--root", required=True)
    add_note_parser.add_argument("--person-id", default="")
    add_note_parser.add_argument("--title", required=True)
    add_note_parser.add_argument("--body", required=True)
    add_note_parser.add_argument("--source-type", default="user")
    add_note_parser.add_argument("--source-label", default="")
    add_note_parser.add_argument("--source-date", default="")
    add_note_parser.set_defaults(func=command_add_note)

    ingest = subparsers.add_parser("ingest-document")
    ingest.add_argument("--root", required=True)
    ingest.add_argument("--person-id", default="")
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--doc-type", required=True)
    ingest.add_argument("--title", default="")
    ingest.add_argument("--source-date", default="")
    ingest.set_defaults(func=command_ingest_document)

    process_inbox_parser = subparsers.add_parser("process-inbox")
    process_inbox_parser.add_argument("--root", required=True)
    process_inbox_parser.add_argument("--person-id", default="")
    process_inbox_parser.set_defaults(func=command_process_inbox)

    list_review_queue = subparsers.add_parser("list-review-queue")
    list_review_queue.add_argument("--root", required=True)
    list_review_queue.add_argument("--person-id", default="")
    list_review_queue.add_argument(
        "--status",
        choices=["open", "applied", "accepted", "rejected"],
        default="",
    )
    list_review_queue.set_defaults(func=command_list_review_queue)

    resolve_review = subparsers.add_parser("resolve-review-item")
    resolve_review.add_argument("--root", required=True)
    resolve_review.add_argument("--person-id", default="")
    resolve_review.add_argument("--review-id", required=True)
    resolve_review.add_argument(
        "--status",
        choices=["accepted", "rejected"],
        required=True,
    )
    resolve_review.add_argument("--note", default="")
    resolve_review.set_defaults(func=command_resolve_review_item)

    apply_review = subparsers.add_parser("apply-review-item")
    apply_review.add_argument("--root", required=True)
    apply_review.add_argument("--person-id", default="")
    apply_review.add_argument("--review-id", required=True)
    apply_review.set_defaults(func=command_apply_review_item)

    apply_review_tier = subparsers.add_parser("apply-review-tier")
    apply_review_tier.add_argument("--root", required=True)
    apply_review_tier.add_argument("--person-id", default="")
    apply_review_tier.add_argument(
        "--tier",
        choices=[
            "safe_to_auto_apply",
            "needs_quick_confirmation",
            "do_not_trust_without_human_review",
        ],
        required=True,
    )
    apply_review_tier.set_defaults(func=command_apply_review_tier)

    resolve_review_tier = subparsers.add_parser("resolve-review-tier")
    resolve_review_tier.add_argument("--root", required=True)
    resolve_review_tier.add_argument("--person-id", default="")
    resolve_review_tier.add_argument(
        "--tier",
        choices=[
            "safe_to_auto_apply",
            "needs_quick_confirmation",
            "do_not_trust_without_human_review",
        ],
        required=True,
    )
    resolve_review_tier.add_argument("--status", choices=["accepted", "rejected"], required=True)
    resolve_review_tier.add_argument("--note", default="")
    resolve_review_tier.set_defaults(func=command_resolve_review_tier)

    render_summary = subparsers.add_parser("render-summary")
    render_summary.add_argument("--root", required=True)
    render_summary.add_argument("--person-id", default="")
    render_summary.set_defaults(func=command_render_summary)

    render_dossier = subparsers.add_parser("render-dossier")
    render_dossier.add_argument("--root", required=True)
    render_dossier.add_argument("--person-id", default="")
    render_dossier.set_defaults(func=command_render_dossier)

    render_home = subparsers.add_parser("render-home")
    render_home.add_argument("--root", required=True)
    render_home.add_argument("--person-id", default="")
    render_home.set_defaults(func=command_render_home)

    render_today = subparsers.add_parser("render-today")
    render_today.add_argument("--root", required=True)
    render_today.add_argument("--person-id", default="")
    render_today.set_defaults(func=command_render_today)

    render_this_week = subparsers.add_parser("render-this-week")
    render_this_week.add_argument("--root", required=True)
    render_this_week.add_argument("--person-id", default="")
    render_this_week.set_defaults(func=command_render_this_week)

    render_next_appointment = subparsers.add_parser("render-next-appointment")
    render_next_appointment.add_argument("--root", required=True)
    render_next_appointment.add_argument("--person-id", default="")
    render_next_appointment.set_defaults(func=command_render_next_appointment)

    render_review_worklist = subparsers.add_parser("render-review-worklist")
    render_review_worklist.add_argument("--root", required=True)
    render_review_worklist.add_argument("--person-id", default="")
    render_review_worklist.set_defaults(func=command_render_review_worklist)

    render_care_status = subparsers.add_parser("render-care-status")
    render_care_status.add_argument("--root", required=True)
    render_care_status.add_argument("--person-id", default="")
    render_care_status.set_defaults(func=command_render_care_status)

    render_intake_summary = subparsers.add_parser("render-intake-summary")
    render_intake_summary.add_argument("--root", required=True)
    render_intake_summary.add_argument("--person-id", default="")
    render_intake_summary.set_defaults(func=command_render_intake_summary)

    render_timeline = subparsers.add_parser("render-timeline")
    render_timeline.add_argument("--root", required=True)
    render_timeline.add_argument("--person-id", default="")
    render_timeline.set_defaults(func=command_render_timeline)

    render_change_report = subparsers.add_parser("render-change-report")
    render_change_report.add_argument("--root", required=True)
    render_change_report.add_argument("--person-id", default="")
    render_change_report.add_argument("--days", type=int, default=30)
    render_change_report.set_defaults(func=command_render_change_report)

    render_trends = subparsers.add_parser("render-trends")
    render_trends.add_argument("--root", required=True)
    render_trends.add_argument("--person-id", default="")
    render_trends.set_defaults(func=command_render_trends)

    record_weight_parser = subparsers.add_parser("record-weight")
    record_weight_parser.add_argument("--root", required=True)
    record_weight_parser.add_argument("--person-id", default="")
    record_weight_parser.add_argument("--value", type=float, required=True)
    record_weight_parser.add_argument("--unit", default="kg")
    record_weight_parser.add_argument("--date", default="")
    record_weight_parser.add_argument("--note", default="")
    record_weight_parser.set_defaults(func=command_record_weight)

    render_weight_trends = subparsers.add_parser("render-weight-trends")
    render_weight_trends.add_argument("--root", required=True)
    render_weight_trends.add_argument("--person-id", default="")
    render_weight_trends.set_defaults(func=command_render_weight_trends)

    record_vital_parser = subparsers.add_parser("record-vital")
    record_vital_parser.add_argument("--root", required=True)
    record_vital_parser.add_argument("--person-id", default="")
    record_vital_parser.add_argument(
        "--metric",
        choices=[
            "blood_pressure",
            "glucose",
            "heart_rate",
            "oxygen_saturation",
            "sleep_hours",
            "symptom_score",
            "adherence",
            "pain_score",
            "mood_score",
            "weight",
        ],
        required=True,
    )
    record_vital_parser.add_argument("--value", required=True)
    record_vital_parser.add_argument("--unit", default="")
    record_vital_parser.add_argument("--date", default="")
    record_vital_parser.add_argument("--note", default="")
    record_vital_parser.set_defaults(func=command_record_vital)

    render_vitals_trends = subparsers.add_parser("render-vitals-trends")
    render_vitals_trends.add_argument("--root", required=True)
    render_vitals_trends.add_argument("--person-id", default="")
    render_vitals_trends.set_defaults(func=command_render_vitals_trends)

    reconcile = subparsers.add_parser("reconcile-medications")
    reconcile.add_argument("--root", required=True)
    reconcile.add_argument("--person-id", default="")
    reconcile.set_defaults(func=command_reconcile_medications)

    export_calendar = subparsers.add_parser("export-calendar")
    export_calendar.add_argument("--root", required=True)
    export_calendar.add_argument("--person-id", default="")
    export_calendar.set_defaults(func=command_export_calendar)

    export_redacted = subparsers.add_parser("export-redacted-summary")
    export_redacted.add_argument("--root", required=True)
    export_redacted.add_argument("--person-id", default="")
    export_redacted.set_defaults(func=command_export_redacted_summary)

    export_clinician_packet = subparsers.add_parser("export-clinician-packet")
    export_clinician_packet.add_argument("--root", required=True)
    export_clinician_packet.add_argument("--person-id", default="")
    export_clinician_packet.add_argument("--visit-type", default="specialist")
    export_clinician_packet.add_argument("--reason", required=True)
    export_clinician_packet.set_defaults(func=command_export_clinician_packet)

    export_portal_message = subparsers.add_parser("export-portal-message")
    export_portal_message.add_argument("--root", required=True)
    export_portal_message.add_argument("--person-id", default="")
    export_portal_message.add_argument("--goal", required=True)
    export_portal_message.set_defaults(func=command_export_portal_message)

    appointment_request = subparsers.add_parser("generate-appointment-request")
    appointment_request.add_argument("--root", required=True)
    appointment_request.add_argument("--person-id", default="")
    appointment_request.add_argument("--specialty", required=True)
    appointment_request.add_argument("--reason", required=True)
    appointment_request.add_argument("--visit-type", default="specialist")
    appointment_request.set_defaults(func=command_generate_appointment_request)

    list_conflicts = subparsers.add_parser("list-conflicts")
    list_conflicts.add_argument("--root", required=True)
    list_conflicts.add_argument("--person-id", default="")
    list_conflicts.add_argument("--status", choices=["open", "resolved"], default="")
    list_conflicts.set_defaults(func=command_list_conflicts)

    resolve = subparsers.add_parser("resolve-conflict")
    resolve.add_argument("--root", required=True)
    resolve.add_argument("--person-id", default="")
    resolve.add_argument("--conflict-id", required=True)
    resolve.add_argument("--resolution", choices=["keep-current", "accept-new"], required=True)
    resolve.add_argument("--note", default="")
    resolve.set_defaults(func=command_resolve_conflict)

    set_preference = subparsers.add_parser("set-preference")
    set_preference.add_argument("--root", required=True)
    set_preference.add_argument("--person-id", default="")
    set_preference.add_argument(
        "--key",
        choices=[
            "summary_style",
            "weight_unit",
            "primary_caregiver",
            "appointment_prep_style",
            "communication_tone",
            "preferred_clinicians",
        ],
        required=True,
    )
    set_preference.add_argument("--value", required=True)
    set_preference.set_defaults(func=command_set_preference)

    backup_project = subparsers.add_parser("backup-project")
    backup_project.add_argument("--root", required=True)
    backup_project.add_argument("--person-id", default="")
    backup_project.set_defaults(func=command_backup_project)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
