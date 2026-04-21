#!/usr/bin/env python3
"""Preventive screening tracker.

Computes which age-/sex-appropriate screenings are due based on profile data.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        calculate_age_from_dob,
        load_profile,
        now_utc,
        save_profile,
        screenings_path,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (
        atomic_write_text,
        calculate_age_from_dob,
        load_profile,
        now_utc,
        save_profile,
        screenings_path,
        workspace_lock,
    )


RECOMMENDED_SCREENINGS: dict[str, dict[str, Any]] = {
    "mammogram": {"frequency_years": 2, "age_start": 40, "age_end": 75, "sex": "female"},
    "colonoscopy": {"frequency_years": 10, "age_start": 45, "age_end": 75, "sex": "any"},
    "cervical_cancer_screening": {"frequency_years": 3, "age_start": 21, "age_end": 65, "sex": "female"},
    "skin_check": {"frequency_years": 1, "age_start": 30, "age_end": 99, "sex": "any"},
    "eye_exam": {"frequency_years": 2, "age_start": 18, "age_end": 99, "sex": "any"},
    "dental_cleaning": {"frequency_years": 0.5, "age_start": 0, "age_end": 99, "sex": "any"},
    "annual_physical": {"frequency_years": 1, "age_start": 18, "age_end": 99, "sex": "any"},
    "lipid_panel": {"frequency_years": 5, "age_start": 20, "age_end": 99, "sex": "any"},
    "blood_pressure": {"frequency_years": 1, "age_start": 18, "age_end": 99, "sex": "any"},
    "bone_density": {"frequency_years": 5, "age_start": 65, "age_end": 99, "sex": "female"},
    "lung_cancer_screening": {"frequency_years": 1, "age_start": 50, "age_end": 80, "sex": "any", "condition": "smoker"},
    "flu_shot": {"frequency_years": 1, "age_start": 6 / 12, "age_end": 99, "sex": "any"},
    "covid_booster": {"frequency_years": 1, "age_start": 5, "age_end": 99, "sex": "any"},
    "tetanus": {"frequency_years": 10, "age_start": 7, "age_end": 99, "sex": "any"},
    "shingles": {"frequency_years": 99, "age_start": 50, "age_end": 99, "sex": "any"},
    "hearing_test": {"frequency_years": 3, "age_start": 60, "age_end": 99, "sex": "any"},
}


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _add_years(d: date, years: float) -> date:
    days = int(round(years * 365.25))
    return d + timedelta(days=days)


def _sex_match(profile_sex: str, required_sex: str) -> bool:
    if required_sex == "any":
        return True
    if not profile_sex:
        # Unknown sex — be generous but skip sex-specific ones
        return False
    return profile_sex.strip().lower().startswith(required_sex.lower()[0])


def _has_condition(profile: dict[str, Any], cond: str) -> bool:
    lowered = cond.lower()
    for item in profile.get("conditions", []):
        name = str(item.get("name", "")).lower()
        if lowered in name:
            return True
    # Check smoker in preferences / notes
    if lowered == "smoker":
        prefs = profile.get("preferences", {})
        if prefs.get("smoker") or prefs.get("is_smoker"):
            return True
    return False


def compute_due_screenings(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of screening statuses for this profile.

    Each item: {name, status, last_date, next_due, reason}
    status: "overdue" | "due_soon" | "up_to_date" | "not_yet" | "not_applicable"
    """
    dob = profile.get("date_of_birth", "")
    sex = profile.get("sex", "")
    age = calculate_age_from_dob(dob) if dob else 0
    today = date.today()

    existing: dict[str, dict[str, Any]] = {}
    for s in profile.get("screenings", []):
        nm = str(s.get("name", "")).strip().lower()
        if nm:
            existing[nm] = s

    results: list[dict[str, Any]] = []

    for name, spec in RECOMMENDED_SCREENINGS.items():
        freq = float(spec["frequency_years"])
        age_start = float(spec["age_start"])
        age_end = float(spec["age_end"])
        required_sex = spec.get("sex", "any")
        condition = spec.get("condition")

        # Sex filter
        if not _sex_match(sex, required_sex):
            continue

        # Condition filter (e.g. smoker)
        if condition and not _has_condition(profile, condition):
            continue

        record = existing.get(name)
        last_date = None
        next_due_str = ""
        reason = ""

        if age < age_start:
            status = "not_yet"
            reason = f"Starts at age {age_start:.0f}; currently {age}."
        elif age > age_end:
            status = "not_applicable"
            reason = f"Typically stops after age {age_end:.0f}."
        else:
            if record and record.get("last_date"):
                last_date = _parse_date(str(record.get("last_date", "")))
            if last_date is None:
                status = "overdue"
                reason = "No record on file — recommended to get scheduled."
            else:
                next_due = _add_years(last_date, freq)
                next_due_str = next_due.isoformat()
                days_to_due = (next_due - today).days
                if days_to_due < 0:
                    status = "overdue"
                    reason = f"Last: {last_date.isoformat()}. Due {-days_to_due} days ago."
                elif days_to_due <= 60:
                    status = "due_soon"
                    reason = f"Last: {last_date.isoformat()}. Due in {days_to_due} days."
                else:
                    status = "up_to_date"
                    reason = f"Last: {last_date.isoformat()}. Next due {next_due_str}."

        results.append({
            "name": name,
            "status": status,
            "last_date": last_date.isoformat() if last_date else (record.get("last_date", "") if record else ""),
            "next_due": next_due_str or (record.get("next_due", "") if record else ""),
            "reason": reason,
            "frequency_years": freq,
        })

    return results


def log_screening(
    root: Path,
    person_id: str,
    name: str,
    date_str: str,
    notes: str = "",
) -> Path:
    """Record a completed screening. Upserts into profile.screenings."""
    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        name_lower = name.strip().lower()

        spec = RECOMMENDED_SCREENINGS.get(name_lower, {})
        freq = float(spec.get("frequency_years", 1))
        last = _parse_date(date_str)
        next_due = _add_years(last, freq).isoformat() if last else ""

        screenings = profile.get("screenings", [])
        found = False
        for s in screenings:
            if str(s.get("name", "")).strip().lower() == name_lower:
                s["last_date"] = date_str
                s["frequency_years"] = freq
                s["next_due"] = next_due
                s["notes"] = notes
                s["status"] = "up_to_date"
                s["last_updated"] = now_utc()
                found = True
                break
        if not found:
            screenings.append({
                "name": name_lower,
                "last_date": date_str,
                "frequency_years": freq,
                "next_due": next_due,
                "status": "up_to_date",
                "notes": notes,
                "source": {"type": "user", "label": "screening-log"},
                "last_updated": now_utc(),
            })
        profile["screenings"] = screenings
        return save_profile(root, person_id, profile)


def render_preventive_care_text(profile: dict[str, Any]) -> str:
    """Render PREVENTIVE_CARE.md grouped by status."""
    results = compute_due_screenings(profile)

    groups: dict[str, list[dict[str, Any]]] = {
        "overdue": [],
        "due_soon": [],
        "up_to_date": [],
        "not_yet": [],
        "not_applicable": [],
    }
    for r in results:
        groups.setdefault(r["status"], []).append(r)

    name = profile.get("name") or "you"
    age = calculate_age_from_dob(profile.get("date_of_birth", ""))

    lines = [
        "# Preventive Care",
        "",
        f"Screenings recommended for {name} (age {age}, sex: {profile.get('sex', 'unspecified') or 'unspecified'}).",
        "",
        "_Guidelines are general. Your clinician may recommend different cadence._",
        "",
    ]

    def _fmt(r: dict[str, Any]) -> str:
        pretty = r["name"].replace("_", " ").title()
        bits = [f"- **{pretty}**"]
        if r.get("last_date"):
            bits.append(f"last: {r['last_date']}")
        if r.get("next_due"):
            bits.append(f"next due: {r['next_due']}")
        if r.get("reason"):
            bits.append(r["reason"])
        return " — ".join(bits)

    section_titles = [
        ("overdue", "## Overdue"),
        ("due_soon", "## Due Soon (next 60 days)"),
        ("up_to_date", "## Up To Date"),
        ("not_yet", "## Coming With Age"),
        ("not_applicable", "## No Longer Recommended"),
    ]
    for key, title in section_titles:
        items = groups.get(key, [])
        if not items:
            continue
        lines.append(title)
        lines.append("")
        for r in items:
            lines.append(_fmt(r))
        lines.append("")

    if not any(groups[k] for k in groups):
        lines.append("No applicable screenings computed — add date of birth and sex to your profile.")
        lines.append("")

    return "\n".join(lines)


def write_preventive_care(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    text = render_preventive_care_text(profile)
    path = screenings_path(root, person_id)
    atomic_write_text(path, text)
    return path
