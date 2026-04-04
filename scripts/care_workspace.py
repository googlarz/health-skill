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
import dataclasses
import hashlib
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


SCHEMA_VERSION = 4

# Valid severity levels for structured allergy records (#14).
ALLERGY_SEVERITY_LEVELS = ("mild", "moderate", "severe", "life-threatening")
ALLERGY_REACTION_TYPES = ("allergy", "intolerance", "adverse-effect")

# Maximum age (months) before records are considered stale (#18).
STALENESS_THRESHOLD_DAYS = 90


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
        "pdf_page_limit": 10,
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


@dataclasses.dataclass
class WorkspaceSnapshot:
    """Pre-loaded workspace state to avoid redundant disk reads (#1)."""

    profile: dict[str, Any]
    conflicts: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]
    medication_history: list[dict[str, Any]]
    weight_entries: list[dict[str, Any]]
    vital_entries: list[dict[str, Any]]
    inbox_files: list[Path]

    # Pre-computed filtered views (computed once, used many times).
    open_conflicts: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    open_review_items: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.open_conflicts = [c for c in self.conflicts if c.get("status") == "open"]
        self.open_review_items = [r for r in self.review_queue if r.get("status", "open") == "open"]


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


def patterns_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_PATTERNS.md"


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

    if not patterns_path(root, person_id).exists():
        atomic_write_text(patterns_path(root, person_id), "# Health Patterns\n\nNot rendered yet.\n")

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
            recorded_at TEXT NOT NULL,
            numeric_value REAL DEFAULT NULL,
            systolic INTEGER DEFAULT NULL,
            diastolic INTEGER DEFAULT NULL
        )
        """
    )
    # Migrate older DBs that lack new columns (#11).
    for col, typedef in [
        ("numeric_value", "REAL DEFAULT NULL"),
        ("systolic", "INTEGER DEFAULT NULL"),
        ("diastolic", "INTEGER DEFAULT NULL"),
    ]:
        try:
            connection.execute(f"ALTER TABLE vital_entries ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    connection.commit()
    return connection


def open_metrics_db(root: Path, person_id: str) -> sqlite3.Connection | None:
    """Read-only DB open — skips CREATE TABLE overhead (#2)."""
    path = metrics_db_path(root, person_id)
    if not path.exists():
        return None
    return sqlite3.connect(path)


def file_content_hash(path: Path) -> str:
    """SHA-256 hash of file contents for dedup (#10)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_bp_values(value_text: str) -> tuple[int | None, int | None]:
    """Parse systolic/diastolic from BP string like '128/82'."""
    match = re.match(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$", str(value_text))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_numeric_from_text(value_text: str) -> float | None:
    """Try to extract a single numeric value from vital text."""
    try:
        return float(value_text)
    except (ValueError, TypeError):
        return None


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
    # Parse structured numeric values at write time (#11).
    numeric_value = parse_numeric_from_text(value_text)
    systolic, diastolic = (None, None)
    if normalized_metric == "blood_pressure":
        systolic, diastolic = parse_bp_values(value_text)
    with ensure_metrics_db(root, person_id) as connection:
        connection.execute(
            """
            INSERT INTO vital_entries
                (entry_date, metric, value_text, unit, note, recorded_at, numeric_value, systolic, diastolic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_date, normalized_metric, value_text, unit, note, now_utc(),
             numeric_value, systolic, diastolic),
        )
        connection.commit()


def load_vital_entries(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = metrics_db_path(root, person_id)
    if not path.exists():
        return []
    with ensure_metrics_db(root, person_id) as connection:
        rows = connection.execute(
            """
            SELECT entry_date, metric, value_text, unit, note, recorded_at,
                   numeric_value, systolic, diastolic
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
            "numeric_value": row[6],
            "systolic": row[7],
            "diastolic": row[8],
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




def list_inbox_files(root: Path, person_id: str) -> list[Path]:
    """List files waiting in the inbox directory."""
    directory = inbox_dir(root, person_id)
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())


def load_snapshot(root: Path, person_id: str) -> WorkspaceSnapshot:
    """Load all workspace data into a single snapshot (#1).

    This avoids repeated disk reads across render functions.
    """
    return WorkspaceSnapshot(
        profile=load_profile(root, person_id),
        conflicts=load_conflicts(root, person_id),
        review_queue=load_review_queue(root, person_id),
        medication_history=load_medication_history(root, person_id),
        weight_entries=load_weight_entries(root, person_id),
        vital_entries=load_vital_entries(root, person_id),
        inbox_files=list_inbox_files(root, person_id),
    )


def document_already_ingested(root: Path, person_id: str, source_path: Path) -> bool:
    """Check if a file with the same content hash was already ingested (#10)."""
    content_hash = file_content_hash(source_path)
    profile = load_profile(root, person_id)
    for doc in profile.get("documents", []):
        if doc.get("content_hash") == content_hash:
            return True
    return False


def archive_old_records(
    root: Path,
    person_id: str,
    max_age_months: int = 12,
) -> Path:
    """Move old test results and encounters to an archive file (#13).

    Keeps the active profile slim. Returns the archive path.
    """
    from dateutil.relativedelta import relativedelta  # noqa: soft dep

    cutoff = (datetime.now(timezone.utc) - relativedelta(months=max_age_months)).date().isoformat()

    profile = load_profile(root, person_id)
    archive_path = person_dir(root, person_id) / "HEALTH_ARCHIVE.json"

    existing_archive: dict[str, list[Any]] = {}
    if archive_path.exists():
        existing_archive = json.loads(archive_path.read_text(encoding="utf-8"))

    for section in ("recent_tests", "encounters", "documents"):
        archived_items = existing_archive.get(section, [])
        active_items = []
        for item in profile.get(section, []):
            item_date = item.get("date") or item.get("source_date") or ""
            if item_date and item_date < cutoff:
                archived_items.append(item)
            else:
                active_items.append(item)
        existing_archive[section] = archived_items
        profile[section] = active_items

    existing_archive["archived_at"] = now_utc()
    existing_archive["cutoff_date"] = cutoff
    atomic_write_text(archive_path, json.dumps(existing_archive, indent=2) + "\n")
    save_profile(root, person_id, profile)
    return archive_path


def staleness_days(profile: dict[str, Any]) -> int:
    """Days since the most recent lab result or encounter (#18)."""
    latest_date = ""
    for item in profile.get("recent_tests", []):
        d = item.get("date") or ""
        if d > latest_date:
            latest_date = d
    for item in profile.get("encounters", []):
        d = item.get("date") or ""
        if d > latest_date:
            latest_date = d
    if not latest_date:
        return 999
    try:
        dt = datetime.strptime(latest_date, "%Y-%m-%d").date()
        return (date.today() - dt).days
    except ValueError:
        return 999


def staleness_warning(profile: dict[str, Any]) -> str | None:
    """Return a warning string if workspace data is stale (#18)."""
    days = staleness_days(profile)
    if days > 180:
        return f"Data may be outdated — the newest recorded result is {days} days old. Consider adding recent labs or visit notes."
    if days > STALENESS_THRESHOLD_DAYS:
        return f"The newest recorded result is {days} days old. Recent data would improve the accuracy of trends and recommendations."
    return None


# Sentinel for project-root mode (one person = one folder).
# Use this instead of bare empty strings for clarity.
PROJECT_ROOT: str = ""


def __getattr__(name: str):
    """Lazy re-export from submodules for backwards compatibility.

    Symbols that were originally in this file but have been moved to
    ``rendering``, ``extraction``, or ``commands`` are transparently
    available here so that existing imports continue to work.
    """
    import importlib  # noqa: delay import

    for module_name in (
        "scripts.rendering",
        "scripts.extraction",
        "scripts.commands",
    ):
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            # Also try non-package form for direct script invocation.
            try:
                mod = importlib.import_module(module_name.split(".")[-1])
            except ImportError:
                continue
        if hasattr(mod, name):
            return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
