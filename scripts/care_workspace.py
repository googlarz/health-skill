#!/usr/bin/env python3
"""Workspace and record management helpers for Health Skill."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import shutil
import sqlite3
import subprocess
import tempfile
import dataclasses
import hashlib
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    import fcntl

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


SCHEMA_VERSION = 5

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
    # v5: Longevity companion sections
    "daily_checkins": [],  # mood, sleep, energy, pain, stress, notes
    "cycles": [],  # period start/end/flow/symptoms (for menstruating users)
    "workouts": [],  # training log entries
    "workout_plans": [],  # structured training programs
    "personal_records": [],  # PRs for lifts, times, distances
    "screenings": [],  # preventive care (mammogram, colonoscopy, etc.)
    "family_history": [],  # parent/sibling conditions for genetic risk
    "goals": [],  # longevity / fitness / health goals with targets
    "preferences": {
        "summary_style": "concise",
        "weight_unit": "kg",
        "primary_caregiver": "",
        "appointment_prep_style": "guided",
        "communication_tone": "calm",
        "preferred_clinicians": [],
        "pdf_page_limit": 10,
        "track_cycles": False,  # explicit opt-in for period tracking
        "onboarded": False,  # has user seen the welcome flow
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
    # v5: Longevity companion
    "daily_checkins": ("date",),
    "cycles": ("start_date",),
    "workouts": ("date", "type"),
    "workout_plans": ("name",),
    "personal_records": ("exercise", "category"),
    "screenings": ("name",),
    "family_history": ("relation", "condition"),
    "goals": ("title",),
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


def dashboard_cache_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "DASHBOARD_CACHE.json"


def extraction_audit_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "EXTRACTION_AUDIT.json"


def onboarding_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "ONBOARDING.md"


def checkins_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "DAILY_CHECKINS.md"


def cycles_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "CYCLES.md"


def training_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "TRAINING.md"


def workout_plan_path(root: Path, person_id: str, plan_name: str) -> Path:
    return person_dir(root, person_id) / f"WORKOUT_PLAN_{slugify(plan_name).upper()}.md"


def screenings_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "PREVENTIVE_CARE.md"


def longevity_dashboard_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "LONGEVITY.html"


def connections_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "CONNECTIONS.md"


def nudges_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "NUDGES.md"


def recap_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "WEEKLY_RECAP.md"


def goals_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "GOALS.md"


def providers_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "PROVIDERS.md"


def triage_path(root: Path, person_id: str, slug: str) -> Path:
    return person_dir(root, person_id) / "notes" / f"{date.today().isoformat()}-triage-{slug}.md"


def forecast_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "HEALTH_FORECAST.md"


def lab_actions_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "LAB_ACTIONS.md"


def nutrition_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "NUTRITION.md"


def nutrition_trends_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "NUTRITION_TRENDS.md"


def decisions_dir(root: Path, person_id: str) -> Path:
    d = exports_dir(root, person_id) / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wearable_inbox(root: Path, person_id: str) -> Path:
    d = person_dir(root, person_id) / "inbox" / "wearable"
    d.mkdir(parents=True, exist_ok=True)
    return d


def household_path(root: Path) -> Path:
    return root / "HOUSEHOLD.json"


def household_dashboard_path(root: Path) -> Path:
    return root / "HOUSEHOLD_DASHBOARD.md"


def extraction_accuracy_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "EXTRACTION_ACCURACY.md"


def reconciliation_path(root: Path, person_id: str) -> Path:
    return exports_dir(root, person_id) / "medication_reconciliation.md"


def calendar_export_path(root: Path, person_id: str) -> Path:
    return exports_dir(root, person_id) / "follow_up_calendar.ics"


def metrics_db_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / "health_metrics.db"


def lock_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / ".health-skill.lock"


def calculate_age_from_dob(dob: str) -> int:
    """Calculate current age in years from a date-of-birth string (YYYY-MM-DD).

    Returns 0 if dob is missing or unparseable.
    """
    if not dob:
        return 0
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(dob.strip(), fmt).date()
            break
        except ValueError:
            dt = None
    if dt is None:
        return 0
    today = date.today()
    years = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    return max(years, 0)


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
    if sys.platform == "win32":
        yield
        return
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
        "hemoglobin a1c": "A1C",
        "tsh": "TSH",
        "bun": "BUN",
        "alt": "ALT",
        "ast": "AST",
        "ldl cholesterol": "LDL",
        "hdl cholesterol": "HDL",
        "total cholesterol": "Total Cholesterol",
        "glucose, fasting": "Glucose (Fasting)",
        "fasting glucose": "Glucose (Fasting)",
        "glucose fasting": "Glucose (Fasting)",
        "vitamin d, 25-oh": "Vitamin D",
        "vitamin d 25-oh": "Vitamin D",
        "vitamin d,25-oh": "Vitamin D",
        "25-oh vitamin d": "Vitamin D",
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


def sync_conflict_count_from(conflicts: list, profile: dict) -> None:
    """Update conflict count from pre-loaded data instead of reading from disk."""
    profile["audit"]["conflicts_open"] = sum(1 for c in conflicts if c["status"] == "open")


def sync_review_count_from(items: list, profile: dict) -> None:
    """Update review count from pre-loaded data instead of reading from disk."""
    profile["audit"]["review_items_open"] = sum(1 for i in items if i.get("status", "open") == "open")


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

    # Medication-allergy safety check (#Item 2)
    if section == "medications":
        med_allergy_conflicts = check_medication_allergy_conflicts(profile)
        for mac in med_allergy_conflicts:
            # Only warn for the medication being added/updated
            if mac["medication"].strip().lower() == str(record.get("name", "")).strip().lower():
                print(
                    f"[SAFETY WARNING] Medication-allergy conflict: {mac['medication']} vs allergy "
                    f"'{mac['allergy']}' (risk: {mac['risk']}). {mac['reason']}"
                )
                create_conflict(
                    root,
                    person_id,
                    "medications",
                    identity,
                    "allergy_conflict",
                    mac["allergy"],
                    mac["medication"],
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


def document_already_ingested(root: Path, person_id: str, source_path: Path, precomputed_hash: str | None = None) -> bool:
    """Check if a file with the same content hash was already ingested (#10)."""
    content_hash = precomputed_hash or file_content_hash(source_path)
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
    cutoff = (date.today() - timedelta(days=max_age_months * 30)).isoformat()

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


# ---------------------------------------------------------------------------
# Dashboard cache: save/reuse query dashboards
# ---------------------------------------------------------------------------

# Maximum age in hours before a cached dashboard is considered stale.
DASHBOARD_CACHE_MAX_AGE_HOURS = 24


def load_dashboard_cache(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = dashboard_cache_path(root, person_id)
    if not path.exists():
        # Try the backup file if the main file doesn't exist
        bak_path = path.with_suffix(path.suffix + ".bak")
        if bak_path.exists():
            try:
                return json.loads(bak_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Main file is corrupted; try the backup
        bak_path = path.with_suffix(path.suffix + ".bak")
        if bak_path.exists():
            try:
                return json.loads(bak_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []


def save_dashboard_cache(root: Path, person_id: str, cache: list[dict[str, Any]]) -> None:
    path = dashboard_cache_path(root, person_id)
    # Save a .bak backup of the existing file before writing
    if path.exists():
        bak_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, bak_path)
        except OSError:
            pass  # Best-effort backup
    atomic_write_text(path, json.dumps(cache, indent=2) + "\n")


def _query_keywords(query: str) -> set[str]:
    """Extract meaningful keywords from a query for similarity matching."""
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "my", "me", "i",
        "do", "does", "did", "what", "how", "when", "where", "why", "which",
        "can", "could", "should", "would", "will", "about", "for", "to",
        "of", "in", "on", "at", "with", "and", "or", "but", "not", "this",
        "that", "it", "be", "have", "has", "had", "been", "from",
    }
    words = set(re.sub(r"[^a-z0-9 ]", " ", query.lower()).split())
    return words - stop_words


MEDICAL_TERMS: set[str] = {
    # Lab names
    "ldl", "hdl", "a1c", "hba1c", "tsh", "bun", "alt", "ast", "creatinine",
    "hemoglobin", "glucose", "cholesterol", "triglycerides", "potassium",
    "sodium", "calcium", "iron", "ferritin", "psa", "cbc", "lipid",
    # Medication names
    "metformin", "atorvastatin", "lisinopril", "amlodipine", "omeprazole",
    "levothyroxine", "simvastatin", "losartan", "gabapentin", "insulin",
    # Condition keywords
    "diabetes", "hypertension", "cholesterol", "thyroid", "anemia",
    "kidney", "liver", "cardiac", "asthma", "copd",
}


def query_similarity(query_a: str, query_b: str) -> float:
    """Jaccard similarity between two queries (0.0-1.0), with medical term boost."""
    kw_a = _query_keywords(query_a)
    kw_b = _query_keywords(query_b)
    if not kw_a or not kw_b:
        return 0.0
    jaccard = len(kw_a & kw_b) / len(kw_a | kw_b)
    # Boost similarity when queries share medical terms
    shared_medical = (kw_a & kw_b) & MEDICAL_TERMS
    if shared_medical:
        jaccard = min(jaccard + 0.2, 1.0)
    return jaccard


def _profile_health_fingerprint(profile: dict[str, Any]) -> str:
    """Hash only the health-critical fields of a profile for cache invalidation."""
    critical_fields = {}
    for key in ("conditions", "medications", "allergies", "recent_tests", "follow_up", "encounters"):
        critical_fields[key] = profile.get(key, [])
    serialized = json.dumps(critical_fields, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def find_cached_dashboard(
    root: Path,
    person_id: str,
    query: str,
    intent: str,
    similarity_threshold: float = 0.3,
    max_age_hours: int = DASHBOARD_CACHE_MAX_AGE_HOURS,
) -> dict[str, Any] | None:
    """Find a cached dashboard matching this query.

    Matches require:
    1. Same intent category
    2. Query similarity >= threshold (Jaccard on keywords)
    3. Cache entry not older than max_age_hours
    4. Profile health-critical fields haven't changed since cache was generated
    """
    cache = load_dashboard_cache(root, person_id)
    if not cache:
        return None

    profile = load_profile(root, person_id)
    current_fingerprint = _profile_health_fingerprint(profile)

    for entry in reversed(cache):  # newest first
        if entry.get("intent") != intent:
            continue

        # Check staleness
        cached_at = entry.get("cached_at", "")
        if cached_at:
            try:
                cached_dt = datetime.fromisoformat(cached_at)
                age_hours = (datetime.now(timezone.utc) - cached_dt).total_seconds() / 3600
                if age_hours > max_age_hours:
                    continue
            except ValueError:
                continue

        # Check if health-critical profile fields changed since cache was created
        cached_fingerprint = entry.get("health_fingerprint", "")
        if cached_fingerprint and current_fingerprint != cached_fingerprint:
            continue

        # Legacy fallback: if no fingerprint in cache, use old timestamp check
        if not cached_fingerprint:
            profile_updated = profile.get("audit", {}).get("updated_at", "")
            cached_profile_updated = entry.get("profile_updated_at", "")
            if profile_updated and cached_profile_updated and profile_updated != cached_profile_updated:
                continue

        # Check similarity
        sim = query_similarity(query, entry.get("query", ""))
        if sim >= similarity_threshold:
            return entry

    return None


def save_dashboard_to_cache(
    root: Path,
    person_id: str,
    query: str,
    intent: str,
    intents_used: list[str],
    dashboard_text: str,
) -> None:
    """Save a dashboard to the cache for future reuse."""
    with workspace_lock(root, person_id):
        cache = load_dashboard_cache(root, person_id)

        # Store profile's current updated_at and health fingerprint.
        profile = load_profile(root, person_id)
        profile_updated_at = profile.get("audit", {}).get("updated_at", "")

        entry = {
            "query": query,
            "intent": intent,
            "intents_used": intents_used,
            "cached_at": now_utc(),
            "profile_updated_at": profile_updated_at,
            "health_fingerprint": _profile_health_fingerprint(profile),
            "dashboard_text": dashboard_text,
            "keywords": sorted(_query_keywords(query)),
        }
        cache.append(entry)

        # Keep only the last 20 entries to prevent unbounded growth.
        if len(cache) > 20:
            cache = cache[-20:]

        save_dashboard_cache(root, person_id, cache)


def record_intent_usage(root: Path, person_id: str, intent: str) -> None:
    """Track which intents the user triggers most (usage learning)."""
    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        usage = profile.get("preferences", {}).get("dashboard_intent_usage", {})
        usage[intent] = usage.get(intent, 0) + 1
        profile.setdefault("preferences", {})["dashboard_intent_usage"] = usage
        save_profile(root, person_id, profile)


def top_intents(root: Path, person_id: str, limit: int = 3) -> list[str]:
    """Return the user's most-used dashboard intents."""
    profile = load_profile(root, person_id)
    usage = profile.get("preferences", {}).get("dashboard_intent_usage", {})
    return sorted(usage, key=usage.get, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Medication–allergy cross-validation (#Item 2)
# ---------------------------------------------------------------------------

KNOWN_DRUG_CLASSES: dict[str, list[str]] = {
    "penicillin": [
        "amoxicillin", "ampicillin", "penicillin", "piperacillin",
        "nafcillin", "oxacillin", "dicloxacillin", "augmentin",
    ],
    "sulfa": [
        "sulfamethoxazole", "sulfasalazine", "bactrim", "septra",
        "trimethoprim-sulfamethoxazole", "dapsone",
    ],
    "cephalosporin": [
        "cephalexin", "cefazolin", "ceftriaxone", "cefdinir",
        "cefuroxime", "cefepime", "cefpodoxime",
    ],
    "nsaid": [
        "ibuprofen", "naproxen", "aspirin", "celecoxib",
        "diclofenac", "meloxicam", "indomethacin", "ketorolac",
    ],
    "statin": [
        "atorvastatin", "rosuvastatin", "simvastatin", "pravastatin",
        "lovastatin", "fluvastatin", "pitavastatin",
    ],
    "ace inhibitor": [
        "lisinopril", "enalapril", "ramipril", "benazepril",
        "captopril", "fosinopril", "quinapril",
    ],
    "opioid": [
        "morphine", "oxycodone", "hydrocodone", "codeine",
        "tramadol", "fentanyl", "methadone", "hydromorphone",
    ],
    "fluoroquinolone": [
        "ciprofloxacin", "levofloxacin", "moxifloxacin",
        "ofloxacin", "norfloxacin",
    ],
}


def _drug_class_for(drug_name: str) -> list[str]:
    """Return all class names a drug belongs to."""
    lowered = drug_name.strip().lower()
    classes = []
    for cls_name, members in KNOWN_DRUG_CLASSES.items():
        if lowered in members or lowered == cls_name:
            classes.append(cls_name)
    return classes


def check_medication_allergy_conflicts(profile: dict) -> list[dict]:
    """Compare active medications against allergies using fuzzy class matching.

    Returns a list of conflict dicts with keys:
        medication, allergy, risk ('high' or 'medium'), reason
    """
    conflicts: list[dict] = []
    medications = profile.get("medications", [])
    allergies = profile.get("allergies", [])

    for med in medications:
        med_name = str(med.get("name", "")).strip().lower()
        if not med_name:
            continue
        med_classes = _drug_class_for(med_name)

        for allergy in allergies:
            substance = str(allergy.get("substance", "")).strip().lower()
            if not substance or substance == "nkda":
                continue

            # Direct name match
            if substance in med_name or med_name in substance:
                conflicts.append({
                    "medication": med.get("name", med_name),
                    "allergy": allergy.get("substance", substance),
                    "risk": "high",
                    "reason": f"Direct match: medication '{med.get('name')}' matches allergy '{allergy.get('substance')}'.",
                })
                continue

            # Class-based fuzzy match
            allergy_classes = _drug_class_for(substance)
            # Also check if allergy substance IS a class name
            if substance in KNOWN_DRUG_CLASSES:
                allergy_classes.append(substance)

            overlap = set(med_classes) & set(allergy_classes)
            if overlap:
                cls_label = ", ".join(sorted(overlap))
                conflicts.append({
                    "medication": med.get("name", med_name),
                    "allergy": allergy.get("substance", substance),
                    "risk": "high",
                    "reason": f"Class match ({cls_label}): '{med.get('name')}' belongs to the same drug class as allergy '{allergy.get('substance')}'.",
                })
                continue

            # Check if allergy substance is a class name and med is a member
            if substance in KNOWN_DRUG_CLASSES and med_name in KNOWN_DRUG_CLASSES[substance]:
                conflicts.append({
                    "medication": med.get("name", med_name),
                    "allergy": allergy.get("substance", substance),
                    "risk": "high",
                    "reason": f"'{med.get('name')}' is a member of the '{substance}' drug class listed as an allergy.",
                })

    return conflicts


# ---------------------------------------------------------------------------
# Extraction audit: measure and improve extraction accuracy
# ---------------------------------------------------------------------------


def load_extraction_audit(root: Path, person_id: str) -> list[dict[str, Any]]:
    path = extraction_audit_path(root, person_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        bak = path.with_suffix(".json.bak")
        if bak.exists():
            try:
                return json.loads(bak.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return []


def save_extraction_audit(root: Path, person_id: str, audit: list[dict[str, Any]]) -> None:
    path = extraction_audit_path(root, person_id)
    bak = path.with_suffix(".json.bak")
    if path.exists():
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass
    atomic_write_text(path, json.dumps(audit, indent=2) + "\n")


def log_extraction_event(
    root: Path,
    person_id: str,
    event_type: str,
    section: str,
    candidate: dict[str, Any],
    confidence: str = "",
    tier: str = "",
    source_title: str = "",
    source_snippet: str = "",
    review_id: str = "",
    resolution: str = "",
    note: str = "",
) -> None:
    """Log an extraction event for accuracy tracking.

    event_type: 'extracted', 'auto_applied', 'accepted', 'rejected', 'applied'

    NOTE: This function does NOT acquire workspace_lock because it is
    typically called from within an already-locked context (command handlers).
    The caller is responsible for holding the lock.
    """
    audit = load_extraction_audit(root, person_id)
    audit.append({
        "timestamp": now_utc(),
        "event_type": event_type,
        "section": section,
        "candidate_summary": _candidate_summary(section, candidate),
        "confidence": confidence,
        "tier": tier,
        "source_title": source_title,
        "source_snippet": (source_snippet or "")[:200],
        "review_id": review_id,
        "resolution": resolution,
        "note": note,
    })
    # Keep last 500 entries
    if len(audit) > 500:
        audit = audit[-500:]
    save_extraction_audit(root, person_id, audit)


def _candidate_summary(section: str, candidate: dict[str, Any]) -> str:
    """One-line summary of a candidate for audit logging."""
    if section == "recent_tests":
        return f"{candidate.get('name', '?')} {candidate.get('value', '?')} {candidate.get('unit', '')}"
    if section == "medications":
        return f"{candidate.get('name', '?')} {candidate.get('dose', '')}"
    if section == "allergies":
        return f"{candidate.get('substance', '?')}"
    if section == "conditions":
        return f"{candidate.get('name', '?')}"
    if section == "follow_up":
        return f"{candidate.get('task', '?')}"
    return str(candidate)[:80]


def compute_extraction_stats(root: Path, person_id: str) -> dict[str, Any]:
    """Compute accuracy statistics from the extraction audit log."""
    audit = load_extraction_audit(root, person_id)
    if not audit:
        return {"total_events": 0, "sections": {}, "overall": {}}

    by_section: dict[str, dict[str, int]] = {}
    for entry in audit:
        section = entry.get("section", "unknown")
        event = entry.get("event_type", "unknown")
        if section not in by_section:
            by_section[section] = {
                "extracted": 0,
                "auto_applied": 0,
                "accepted": 0,
                "rejected": 0,
                "applied": 0,
            }
        counts = by_section[section]
        if event in counts:
            counts[event] += 1

    section_stats = {}
    totals = {"extracted": 0, "auto_applied": 0, "accepted": 0, "rejected": 0, "applied": 0}
    for section, counts in by_section.items():
        reviewed = counts["accepted"] + counts["rejected"]
        accepted = counts["accepted"] + counts["applied"] + counts["auto_applied"]
        total_out = counts["extracted"]
        accuracy = round(accepted / reviewed * 100, 1) if reviewed > 0 else None
        rejection_rate = round(counts["rejected"] / reviewed * 100, 1) if reviewed > 0 else None
        section_stats[section] = {
            **counts,
            "reviewed": reviewed,
            "accuracy_pct": accuracy,
            "rejection_rate_pct": rejection_rate,
        }
        for k in totals:
            totals[k] += counts.get(k, 0)

    total_reviewed = totals["accepted"] + totals["rejected"]
    total_accepted = totals["accepted"] + totals["applied"] + totals["auto_applied"]
    overall_accuracy = round(total_accepted / total_reviewed * 100, 1) if total_reviewed > 0 else None
    overall_rejection = round(totals["rejected"] / total_reviewed * 100, 1) if total_reviewed > 0 else None

    return {
        "total_events": len(audit),
        "sections": section_stats,
        "overall": {
            **totals,
            "reviewed": total_reviewed,
            "accuracy_pct": overall_accuracy,
            "rejection_rate_pct": overall_rejection,
        },
    }


def render_extraction_accuracy_text(stats: dict[str, Any]) -> str:
    """Render EXTRACTION_ACCURACY.md from computed stats."""
    lines = [
        "# Extraction Accuracy",
        "",
    ]
    if stats["total_events"] == 0:
        lines.append("No extraction events recorded yet. Process some documents to start tracking accuracy.")
        lines.append("")
        return "\n".join(lines)

    overall = stats["overall"]
    lines.extend([
        "## Overall",
        f"- Total extraction events: {stats['total_events']}",
        f"- Extracted: {overall['extracted']} | Auto-applied: {overall['auto_applied']}",
        f"- Reviewed: {overall['reviewed']} (accepted: {overall['accepted']}, rejected: {overall['rejected']})",
        f"- Applied after review: {overall['applied']}",
    ])
    if overall["accuracy_pct"] is not None:
        lines.append(f"- **Acceptance rate: {overall['accuracy_pct']}%**")
    if overall["rejection_rate_pct"] is not None:
        lines.append(f"- Rejection rate: {overall['rejection_rate_pct']}%")
    lines.append("")

    lines.append("## By Section")
    for section, s in sorted(stats["sections"].items()):
        lines.extend([
            f"### {section}",
            f"- Extracted: {s['extracted']} | Auto-applied: {s['auto_applied']}",
            f"- Reviewed: {s['reviewed']} (accepted: {s['accepted']}, rejected: {s['rejected']})",
        ])
        if s["accuracy_pct"] is not None:
            lines.append(f"- Acceptance rate: {s['accuracy_pct']}%")
        if s["rejection_rate_pct"] is not None and s["rejection_rate_pct"] > 30:
            lines.append(f"- ⚠ High rejection rate ({s['rejection_rate_pct']}%) — extraction patterns for {section} may need improvement")
        lines.append("")

    lines.extend([
        "## What This Means",
        "- High acceptance rate (>80%) means extraction patterns are working well for that section.",
        "- High rejection rate (>30%) means the patterns are producing false positives — the regexes may need tightening.",
        "- Sections with many extractions but zero reviews have unconfirmed data in the record.",
        "",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session change detection (#Item 3)
# ---------------------------------------------------------------------------


def session_marker_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / ".last_session"


def mark_session(root: Path, person_id: str) -> None:
    """Write current timestamp to .last_session marker file."""
    atomic_write_text(session_marker_path(root, person_id), now_utc() + "\n")


def changes_since_last_session(root: Path, person_id: str) -> dict[str, Any]:
    """Return a dict describing what changed since the last session marker.

    Keys:
        last_session: ISO timestamp string or None
        days_ago: float days since last session or None
        new_notes: count of notes created after last session
        new_documents: count of documents ingested after last session
        profile_changes: list of section names that changed
        new_review_items: count of review items created after last session
        resolved_items: count of items resolved after last session
    """
    marker = session_marker_path(root, person_id)
    last_session: str | None = None
    last_dt: datetime | None = None
    if marker.exists():
        raw = marker.read_text(encoding="utf-8").strip()
        if raw:
            last_session = raw
            try:
                last_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                last_dt = None

    result: dict[str, Any] = {
        "last_session": last_session,
        "days_ago": None,
        "new_notes": 0,
        "new_documents": 0,
        "profile_changes": [],
        "new_review_items": 0,
        "resolved_items": 0,
    }

    if last_dt is None:
        return result

    now = datetime.now(timezone.utc)
    result["days_ago"] = round((now - last_dt).total_seconds() / 86400, 1)
    cutoff = last_session  # ISO string comparison

    # Count new notes by file modification time
    nd = notes_dir(root, person_id)
    if nd.exists():
        for note_path in nd.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(note_path.stat().st_mtime, tz=timezone.utc)
                if mtime > last_dt:
                    result["new_notes"] += 1
            except OSError:
                pass

    # Count new documents from profile
    profile = load_profile(root, person_id)
    for doc in profile.get("documents", []):
        doc_date = doc.get("last_updated") or doc.get("source_date") or ""
        if doc_date and doc_date > cutoff:
            result["new_documents"] += 1

    # Check profile updated_at vs last session
    profile_updated = profile.get("audit", {}).get("updated_at", "")
    if profile_updated and profile_updated > cutoff:
        # Identify which sections have recent updates
        for section in RECORD_KEYS:
            for item in profile.get(section, []):
                item_updated = item.get("last_updated", "")
                if item_updated and item_updated > cutoff:
                    if section not in result["profile_changes"]:
                        result["profile_changes"].append(section)
                    break

    # Count new and resolved review items
    review_queue = load_review_queue(root, person_id)
    for item in review_queue:
        detected = item.get("detected_at", "")
        if detected and detected > cutoff and item.get("status", "open") == "open":
            result["new_review_items"] += 1
        resolved = item.get("resolved_at", "")
        if resolved and resolved > cutoff and item.get("status") != "open":
            result["resolved_items"] += 1

    return result


# Sentinel for project-root mode (one person = one folder).
# Use this instead of bare empty strings for clarity.
PROJECT_ROOT: str = ""


def main() -> int:
    """CLI entry point — delegates to commands module."""
    try:
        from scripts.commands import main as commands_main
    except ImportError:
        from commands import main as commands_main
    return commands_main()


if __name__ == "__main__":
    raise SystemExit(main())


