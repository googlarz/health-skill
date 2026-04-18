#!/usr/bin/env python3
"""Rendering and view generation for Health Skill workspaces."""

from __future__ import annotations

import dataclasses
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# NOTE: keep both import blocks in sync
try:
    from .care_workspace import (
        RECORD_KEYS,
        STALENESS_THRESHOLD_DAYS,
        WorkspaceSnapshot,
        archive_dir,
        atomic_write_text,
        calendar_export_path,
        care_status_path,
        change_report_path,
        changes_since_last_session,
        check_medication_allergy_conflicts,
        dossier_path,
        exports_dir,
        home_path,
        list_inbox_files,
        load_conflicts,
        load_medication_history,
        load_profile,
        load_review_queue,
        load_snapshot,
        load_vital_entries,
        load_weight_entries,
        mark_session,
        notes_dir,
        normalize_test_name,
        now_utc,
        parse_bp_values,
        patterns_path,
        person_dir,
        reconciliation_path,
        review_worklist_path,
        save_profile,
        staleness_warning,
        start_here_path,
        summary_path,
        sync_conflict_count,
        sync_conflict_count_from,
        sync_review_count,
        sync_review_count_from,
        this_week_path,
        timeline_path,
        today_path,
        trends_path,
        vitals_trends_path,
        weight_trends_path,
        assistant_update_path,
        next_appointment_path,
        intake_summary_path,
    )
except ImportError:
    from care_workspace import (
        RECORD_KEYS,
        STALENESS_THRESHOLD_DAYS,
        WorkspaceSnapshot,
        archive_dir,
        atomic_write_text,
        calendar_export_path,
        care_status_path,
        change_report_path,
        changes_since_last_session,
        check_medication_allergy_conflicts,
        dossier_path,
        exports_dir,
        home_path,
        list_inbox_files,
        load_conflicts,
        load_medication_history,
        load_profile,
        load_review_queue,
        load_snapshot,
        load_vital_entries,
        load_weight_entries,
        mark_session,
        notes_dir,
        normalize_test_name,
        now_utc,
        parse_bp_values,
        patterns_path,
        person_dir,
        reconciliation_path,
        review_worklist_path,
        save_profile,
        staleness_warning,
        start_here_path,
        summary_path,
        sync_conflict_count,
        sync_conflict_count_from,
        sync_review_count,
        sync_review_count_from,
        this_week_path,
        timeline_path,
        today_path,
        trends_path,
        vitals_trends_path,
        weight_trends_path,
        assistant_update_path,
        next_appointment_path,
        intake_summary_path,
    )


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
    return f"\u2705 {positive}" if ok else f"\u26a0\ufe0f {needs_attention}"


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


def parse_blood_pressure(value_text: str) -> tuple[int | None, int | None]:
    match = re.match(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$", str(value_text))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def latest_medication_change(medication_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not medication_history:
        return None
    return sorted(medication_history, key=lambda item: item.get("recorded_at", ""))[-1]


def build_pattern_insights(
    profile: dict[str, Any],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
) -> list[str]:
    insights: list[str] = []

    grouped_tests: dict[str, list[dict[str, Any]]] = {}
    for item in profile.get("recent_tests", []):
        value = parse_numeric_value(item.get("value"))
        if value is None:
            continue
        name = normalize_test_name(str(item.get("name", "")))
        grouped_tests.setdefault(name, []).append(item)

    for name in sorted(grouped_tests):
        series = sorted(grouped_tests[name], key=lambda item: item.get("date", ""))
        if len(series) < 2:
            continue
        first = parse_numeric_value(series[0].get("value"))
        latest = parse_numeric_value(series[-1].get("value"))
        if first is None or latest is None:
            continue
        delta = latest - first
        threshold = TREND_THRESHOLDS.get(name, 0.0)
        if threshold and abs(delta) >= threshold:
            direction = "up" if delta > 0 else "down"
            insights.append(
                f"{name} has moved {direction} by {abs(delta):.2f} {series[-1].get('unit', '')} across the recorded series."
            )
        abnormal_count = sum(1 for item in series if item.get("flag") in {"high", "low", "abnormal"})
        if abnormal_count >= 2:
            insights.append(
                f"{name} has been flagged abnormal on multiple recorded dates, which suggests a repeat pattern rather than a one-off result."
            )

    if len(weight_entries) >= 2:
        first = weight_entries[0]["value"]
        latest = weight_entries[-1]["value"]
        if first:
            change_pct = ((latest - first) / first) * 100
            if abs(change_pct) >= 5:
                insights.append(
                    f"Weight changed by {change_pct:+.1f}% between the first and latest recorded entries."
                )

    bp_entries = [item for item in vital_entries if item.get("metric") == "blood_pressure"]
    elevated_bp = 0
    for item in bp_entries:
        systolic, diastolic = parse_blood_pressure(str(item.get("value_text", "")))
        if systolic is None:
            continue
        if systolic >= 130 or diastolic >= 80:
            elevated_bp += 1
    if elevated_bp >= 2:
        insights.append(
            f"Blood pressure has been elevated in {elevated_bp} recorded entries, which may be worth discussing as a repeated pattern."
        )

    med_change = latest_medication_change(medication_history)
    if med_change:
        change_time = parse_date_like(str(med_change.get("recorded_at", "")))
        if change_time:
            nearby_abnormal = [
                item
                for item in profile.get("recent_tests", [])
                if item.get("flag") in {"high", "low", "abnormal"}
                and (test_time := parse_date_like(str(item.get("date", ""))))
                and 0 <= (test_time - change_time).days <= 45
            ]
            if nearby_abnormal:
                insights.append(
                    f"There are abnormal labs recorded within about 45 days after the medication change to {med_change.get('medication_name')}, so that timing may be worth reviewing."
                )

    overdue = [
        item
        for item in profile.get("follow_up", [])
        if item.get("status") != "done"
        and item.get("due_date")
        and item.get("due_date") < date.today().isoformat()
    ]
    if overdue and recent_abnormal_tests(profile, limit=10):
        insights.append(
            f"There are both abnormal findings and overdue follow-ups on record, which suggests the issue may be lingering without a closed loop."
        )

    # --- Time-gap awareness (#15a) ---
    today_dt = date.today()
    for name in sorted(grouped_tests):
        series = sorted(grouped_tests[name], key=lambda item: item.get("date", ""))
        if not series:
            continue
        newest = series[-1]
        newest_date = parse_date_like(str(newest.get("date", "")))
        if newest_date is None:
            continue
        months_ago = (today_dt - newest_date.date()).days / 30.0
        if months_ago >= 6 and newest.get("flag") in {"high", "low", "abnormal"}:
            insights.append(
                f"{name} was last checked {int(months_ago)} months ago and was abnormal — may be due for a repeat."
            )

    # --- Medication-lab correlation (#15b) ---
    _MED_LAB_PAIRS: dict[str, tuple[str, ...]] = {
        "atorvastatin": ("LDL",),
        "rosuvastatin": ("LDL",),
        "simvastatin": ("LDL",),
        "pravastatin": ("LDL",),
        "metformin": ("A1C",),
        "levothyroxine": ("TSH",),
        "lisinopril": ("blood_pressure",),
        "losartan": ("blood_pressure",),
        "amlodipine": ("blood_pressure",),
    }
    active_meds = {
        str(m.get("name", "")).strip().lower()
        for m in profile.get("medications", [])
        if str(m.get("status", "")).lower() in {"active", "current", ""}
    }
    for med_name, lab_targets in _MED_LAB_PAIRS.items():
        if med_name not in active_meds:
            continue
        for lab in lab_targets:
            if lab == "blood_pressure":
                if elevated_bp >= 2:
                    insights.append(
                        f"{med_name.title()} is active but blood pressure has been elevated in {elevated_bp} entries — worth reviewing effectiveness."
                    )
            elif lab in grouped_tests:
                lab_series = sorted(grouped_tests[lab], key=lambda item: item.get("date", ""))
                if len(lab_series) >= 2:
                    first_v = parse_numeric_value(lab_series[0].get("value"))
                    last_v = parse_numeric_value(lab_series[-1].get("value"))
                    if first_v is not None and last_v is not None:
                        threshold = TREND_THRESHOLDS.get(lab, 0.0)
                        delta = last_v - first_v
                        if lab == "LDL" and delta > 0 and threshold and abs(delta) >= threshold:
                            insights.append(
                                f"{med_name.title()} is active but {lab} has trended up by {abs(delta):.1f} — worth reviewing."
                            )
                        elif lab == "A1C" and delta > 0 and threshold and abs(delta) >= threshold:
                            insights.append(
                                f"{med_name.title()} is active but {lab} has trended up by {abs(delta):.1f} — worth reviewing."
                            )
                        elif lab == "TSH":
                            abnormal_count = sum(
                                1 for item in lab_series if item.get("flag") in {"high", "low", "abnormal"}
                            )
                            if abnormal_count >= 1 and threshold and abs(delta) >= threshold:
                                insights.append(
                                    f"{med_name.title()} is active but {lab} has shifted by {abs(delta):.2f} with abnormal flags — dose review may help."
                                )

    # --- Test ordering cadence (#15c) ---
    test_names_recorded = {
        normalize_test_name(str(t.get("name", "")))
        for t in profile.get("recent_tests", [])
        if t.get("name")
    }
    for fu_item in overdue:
        task_text = str(fu_item.get("task", "")).lower()
        if "repeat" in task_text or "recheck" in task_text:
            # Try to find a test name mentioned in the task
            for tname in test_names_recorded:
                if tname.lower() in task_text:
                    # Check if the test appeared after the due date
                    due_str = str(fu_item.get("due_date", ""))
                    has_newer = any(
                        t.get("date", "") >= due_str
                        for t in profile.get("recent_tests", [])
                        if normalize_test_name(str(t.get("name", ""))) == tname
                    )
                    if not has_newer:
                        insights.append(
                            f"A follow-up to recheck {tname} was due {due_str} but no result has appeared since."
                        )
                    break

    # --- Temporal side-effect correlation (#Item 4 + #Item 12) ---
    _SYMPTOM_KEYWORDS = {
        "pain", "nausea", "fatigue", "rash", "dizziness", "headache",
        "muscle", "ache", "swelling", "vomiting", "itching", "insomnia",
    }
    # Build a map of medication start dates from medication_history
    med_start_dates: dict[str, datetime] = {}
    for hist_entry in medication_history:
        if hist_entry.get("event_type") == "added":
            med_name_h = str(hist_entry.get("medication_name", "")).strip().lower()
            recorded = parse_date_like(str(hist_entry.get("recorded_at", "")))
            if med_name_h and recorded:
                # Keep the earliest add date
                if med_name_h not in med_start_dates or recorded < med_start_dates[med_name_h]:
                    med_start_dates[med_name_h] = recorded

    if med_start_dates:
        # Gather encounter / note dates with symptom mentions
        symptom_events: list[tuple[datetime, set[str]]] = []
        for enc in profile.get("encounters", []):
            enc_date = parse_date_like(str(enc.get("date", "")))
            if not enc_date:
                continue
            text_blob = f"{enc.get('title', '')} {enc.get('summary', '')}".lower()
            found_symptoms = {kw for kw in _SYMPTOM_KEYWORDS if kw in text_blob}
            if found_symptoms:
                symptom_events.append((enc_date, found_symptoms))

        for med_name_lower, start_dt in med_start_dates.items():
            for evt_dt, syms in symptom_events:
                days_after = (evt_dt - start_dt).days
                if 30 <= days_after <= 90:
                    sym_list = ", ".join(sorted(syms))
                    med_display = med_name_lower.title()
                    insights.append(
                        f"Symptoms ({sym_list}) appeared ~{days_after} days after starting {med_display}. "
                        f"This timing may be worth discussing with a clinician."
                    )
                    break  # one flag per medication is enough

    deduped: list[str] = []
    for item in insights:
        if item not in deduped:
            deduped.append(item)
    return deduped[:10]


def render_patterns_text(
    profile: dict[str, Any],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
) -> str:
    insights = build_pattern_insights(profile, medication_history, weight_entries, vital_entries)
    lines = ["# Health Patterns", ""]
    if not insights:
        lines.append("No cross-record patterns are clear yet. Add more history, labs, vitals, or medication changes to make this view more useful.")
        lines.append("")
        return "\n".join(lines)
    lines.append("These are practical cross-record connections surfaced from the current workspace history.")
    lines.append("")
    lines.append("## Pattern Signals")
    lines.extend(f"- {item}" for item in insights)
    lines.append("")
    return "\n".join(lines)


def _trend_arrow(delta: float) -> str:
    """Return a Unicode arrow indicating trend direction."""
    if delta > 0:
        return "\u2191"
    elif delta < 0:
        return "\u2193"
    return "\u2192"


def _range_bar(value: float, ref_low: float, ref_high: float, width: int = 8) -> str:
    """Render a simple bar showing where value falls relative to reference range."""
    if ref_high <= ref_low:
        return ""
    # Extend range to show out-of-range values
    span = ref_high - ref_low
    display_low = ref_low - span * 0.3
    display_high = ref_high + span * 0.3
    display_span = display_high - display_low
    if display_span <= 0:
        return ""
    pos = int(((value - display_low) / display_span) * width)
    pos = max(0, min(width - 1, pos))
    bar = ["\u2591"] * width  # light shade
    # Fill from 0 to pos
    for i in range(pos + 1):
        bar[i] = "\u2588"  # full block
    return "".join(bar)


def _parse_reference_range(ref: str) -> tuple[float | None, float | None]:
    """Parse a reference range string like '0-99' or '< 100' into (low, high)."""
    if not ref:
        return None, None
    match = re.match(r"^\s*(\d+\.?\d*)\s*[-\u2013]\s*(\d+\.?\d*)\s*$", ref)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.match(r"^\s*<\s*(\d+\.?\d*)\s*$", ref)
    if match:
        return 0.0, float(match.group(1))
    match = re.match(r"^\s*>\s*(\d+\.?\d*)\s*$", ref)
    if match:
        return float(match.group(1)), None
    return None, None


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
        arrow = ""
        if latest_value is not None and earliest_value is not None and len(series) > 1:
            delta = latest_value - earliest_value
            change = f" | change {delta:+.2f}"
            arrow = f" {_trend_arrow(delta)}"
            threshold = TREND_THRESHOLDS.get(name, 0.0)
            if threshold and abs(delta) >= threshold:
                significance = " | notable trend"

        unit = latest.get("unit", "")
        unit_suffix = f" {unit}" if unit else ""
        lines.append(f"## {name}")
        lines.append(
            f"- Latest: **{latest.get('value')}{unit_suffix}** on {latest.get('date') or 'unknown'}"
            f"{change}{significance}"
        )

        # Range bar if reference range is available
        ref_str = latest.get("reference_range", "")
        ref_low, ref_high = _parse_reference_range(str(ref_str))
        if ref_low is not None and ref_high is not None and latest_value is not None:
            bar = _range_bar(latest_value, ref_low, ref_high)
            values_in_series = [parse_numeric_value(i.get("value")) for i in series]
            values_in_series = [v for v in values_in_series if v is not None]
            lo = min(values_in_series) if values_in_series else latest_value
            hi = max(values_in_series) if values_in_series else latest_value
            lines.append(f"- Range: {bar} ({lo:.0f}-{hi:.0f} out of ref {ref_low:.0f}-{ref_high:.0f})")
        elif ref_str:
            lines.append(f"- Reference range: {ref_str}")

        if latest.get("flag"):
            flag = latest.get("flag")
            flag_icon = "\u26a0\ufe0f" if flag in ("high", "low", "abnormal") else ""
            lines.append(f"- Latest flag: {flag_icon} {flag}")

        # Trend line with arrows for series with 2+ values
        if len(series) >= 2:
            trend_values = " \u2192 ".join(
                str(item.get("value", "?")) for item in series
            )
            lines.append(f"- Trend: {trend_values}{arrow}")
        else:
            lines.append(
                f"- Series: {series[0].get('date', 'unknown')}={series[0].get('value')}"
                f"{(' ' + series[0].get('unit')) if series[0].get('unit') else ''}"
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


def _sparkline(values: list[float], width: int = 7) -> str:
    """Render a Unicode sparkline from a list of numeric values."""
    if not values or len(values) < 2:
        return ""
    blocks = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return blocks[3] * min(len(values), width)
    # Resample to width if needed
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values
    result = []
    for v in sampled:
        idx = int(((v - lo) / span) * (len(blocks) - 1))
        idx = max(0, min(len(blocks) - 1, idx))
        result.append(blocks[idx])
    return "".join(result)


def render_weight_trends_text(entries: list[dict[str, Any]]) -> str:
    lines = ["# Weight Trend", ""]
    if not entries:
        lines.append("No weight entries yet.")
        lines.append("")
        return "\n".join(lines)

    latest = entries[-1]
    lines.append(
        f"- Latest: **{latest['value']} {latest['unit']}** ({latest['entry_date']})"
    )
    if len(entries) > 1:
        first_val = entries[0]["value"]
        latest_val = latest["value"]
        delta = latest_val - first_val
        pct = ((delta / first_val) * 100) if first_val else 0
        arrow = _trend_arrow(delta)
        lines.append(
            f"- Change: {first_val} \u2192 {latest_val} ({pct:+.1f}%) {arrow}"
        )
        # Sparkline
        values = [e["value"] for e in entries if e.get("value") is not None]
        spark = _sparkline(values)
        if spark:
            lines.append(f"- Trend: {spark}")
    lines.append("")
    lines.append("## Series")
    lines.extend(
        f"- {item['entry_date']} | {item['value']} {item['unit']}"
        + (f" | {item['note']}" if item.get("note") else "")
        for item in entries
    )
    lines.append("")
    return "\n".join(lines)


def _bp_status_icon(systolic: int | None, diastolic: int | None) -> str:
    """Return a status icon for blood pressure reading."""
    if systolic is None or diastolic is None:
        return ""
    if systolic < 120 and diastolic < 80:
        return "\u2705"
    if systolic < 130 and diastolic < 85:
        return "\u2705"
    if systolic < 140 and diastolic < 90:
        return "\u26a0\ufe0f"
    return "\u274c"


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
        metric_entries = grouped[metric]
        display_name = metric.replace("_", " ").title()
        latest = metric_entries[-1]
        unit = f" {latest['unit']}" if latest.get("unit") else ""

        lines.append(f"## {display_name}")

        # Latest with status indicator
        if metric == "blood_pressure":
            sys_val = latest.get("systolic")
            dia_val = latest.get("diastolic")
            icon = _bp_status_icon(sys_val, dia_val)
            lines.append(
                f"- Latest: **{latest['value_text']}{unit}** {icon} ({latest['entry_date']})"
            )
        else:
            lines.append(
                f"- Latest: **{latest['value_text']}{unit}** ({latest['entry_date']})"
            )

        # History trend line for 2+ entries
        if len(metric_entries) >= 2:
            history_values = [e["value_text"] for e in metric_entries[-6:]]
            trend_line = " \u2192 ".join(history_values)
            # Determine overall direction
            if metric == "blood_pressure":
                first_sys = metric_entries[0].get("systolic")
                last_sys = latest.get("systolic")
                if first_sys is not None and last_sys is not None:
                    arrow = _trend_arrow(last_sys - first_sys)
                    trend_line += f" {arrow}"
            else:
                first_num = metric_entries[0].get("numeric_value")
                last_num = latest.get("numeric_value")
                if first_num is not None and last_num is not None:
                    arrow = _trend_arrow(last_num - first_num)
                    trend_line += f" {arrow}"
            lines.append(f"- History: {trend_line}")
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
    pattern_insights = build_pattern_insights(profile, medication_history, weight_entries, vital_entries)

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
    lines.extend(["", "## Cross-Record Connections"])
    if pattern_insights:
        lines.extend(f"- {item}" for item in pattern_insights[:4])
    else:
        lines.append("- none recorded")
    lines.append("")
    return "\n".join(lines)


def render_session_diff_text(changes: dict[str, Any]) -> str:
    """Render a human-friendly summary of what changed since the last session."""
    last = changes.get("last_session")
    if not last:
        return ""

    days_ago = changes.get("days_ago")
    if days_ago is None:
        return ""

    # Format the time-ago string
    if days_ago < 1:
        time_ago = "earlier today"
    elif days_ago < 2:
        time_ago = "yesterday"
    else:
        time_ago = f"{int(days_ago)} days ago"

    items: list[str] = []
    new_docs = changes.get("new_documents", 0)
    new_notes = changes.get("new_notes", 0)
    new_reviews = changes.get("new_review_items", 0)
    resolved = changes.get("resolved_items", 0)
    profile_changes = changes.get("profile_changes", [])

    if new_docs:
        items.append(f"\U0001f4c4 {new_docs} new document(s) processed")
    if new_notes:
        items.append(f"\U0001f4dd {new_notes} new note(s) added")
    if new_reviews:
        items.append(f"\u26a0\ufe0f {new_reviews} item(s) need your review")
    if resolved:
        items.append(f"\u2705 {resolved} review item(s) resolved")
    if profile_changes:
        section_labels = {
            "recent_tests": "lab results",
            "medications": "medication list",
            "conditions": "conditions",
            "follow_up": "follow-up tasks",
            "allergies": "allergies",
            "clinicians": "clinician list",
            "encounters": "encounters",
        }
        changed_labels = [section_labels.get(s, s) for s in profile_changes]
        items.append(f"\U0001f4ca Updated: {', '.join(changed_labels)}")

    if not items:
        return ""

    lines = [
        f"## Since Your Last Session ({time_ago})",
    ]
    lines.extend(f"- {item}" for item in items)
    lines.append("")
    return "\n".join(lines)


def render_start_here_text(
    profile: dict[str, Any],
    inbox_files: list[Path] | None = None,
    review_queue: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    session_changes: dict[str, Any] | None = None,
) -> str:
    name = profile.get("name") or profile.get("person_id") or "this person"
    inbox_files = inbox_files or []
    review_queue = review_queue or []
    conflicts = conflicts or []
    open_review_items = open_reviews(review_queue)
    nf = next_follow_up(profile)

    lines = [
        f"# {name}",
        "",
    ]

    # Session diff if available
    if session_changes:
        diff_text = render_session_diff_text(session_changes)
        if diff_text:
            lines.append(diff_text)

    # Actionable status lines
    action_lines: list[str] = []
    if inbox_files:
        action_lines.append(f"You have **{len(inbox_files)}** file(s) in inbox.")
    if open_review_items:
        action_lines.append(f"**{len(open_review_items)}** item(s) need your review.")
    if nf:
        action_lines.append(f"Next follow-up: **{nf.get('task')}** on {nf.get('due_date', 'unknown')}.")
    due_now = due_follow_ups(profile, days=0)
    if due_now:
        action_lines.append(f"**{len(due_now)}** follow-up(s) are overdue.")

    if action_lines:
        lines.extend(f"- {item}" for item in action_lines[:3])
    else:
        lines.append("Everything looks good. No urgent actions right now.")
    lines.append("")
    lines.append("Open TODAY.md for today's priorities, or HEALTH_HOME.md for the full picture.")
    lines.append("")
    return "\n".join(lines)


_SECTION_DIVIDER = "\u2500" * 40


def render_health_home_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    inbox_files: list[Path],
    review_queue: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
) -> str:
    next_item = next_follow_up(profile)
    pattern_insights = build_pattern_insights(profile, medication_history, weight_entries, vital_entries)
    stale = staleness_warning(profile)
    open_review_items = open_reviews(review_queue)
    open_conflict_items = open_conflicts_only(conflicts)

    # Status bar at top
    inbox_chip = status_chip(not inbox_files, "Inbox clear", f"{len(inbox_files)} file(s) in inbox")
    review_chip = status_chip(not open_review_items, "No items need review", f"{len(open_review_items)} items need review")
    followup_chip = status_chip(
        not due_follow_ups(profile, days=0),
        "No overdue follow-ups",
        f"{len(due_follow_ups(profile, days=0))} overdue follow-ups",
    )

    lines = [
        "# Health Home",
        "",
    ]
    if stale:
        lines.append(f"> {stale}")
        lines.append("")
    lines.extend([
        f"{inbox_chip} | {review_chip} | {followup_chip}",
        "",
        _SECTION_DIVIDER,
        "",
        "This is the calmest place to start if you just want to know what matters now.",
        "",
        "## Right Now",
    ])
    lines.extend(f"- {item}" for item in current_priorities(profile, conflicts, inbox_files, review_queue))
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Snapshot",
        f"- Person: **{profile.get('name') or profile.get('person_id') or 'unknown'}**",
        f"- Latest weight: **{latest_weight_summary(weight_entries)}**",
        f"- Next follow-up: {render_record(next_item, ('task', 'due_date', 'status')) if next_item else 'none recorded'}",
        f"- Open review items: **{len(open_review_items)}**",
        f"- Open conflicts: **{len(open_conflict_items)}**",
        "",
        _SECTION_DIVIDER,
        "",
        "## Recent Signal",
    ])
    abnormal = recent_abnormal_tests(profile, limit=3)
    if abnormal:
        lines.extend(
            f"- \u26a0\ufe0f **{item.get('name')}** {item.get('value')} {item.get('unit', '')} ({item.get('flag') or '?'}) | trust: {source_trust_label(item.get('source'))}"
            for item in abnormal
        )
    else:
        lines.append("- \u2705 No abnormal lab flags are currently highlighted.")
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Connected Patterns",
    ])
    if pattern_insights:
        lines.extend(f"- {item}" for item in pattern_insights[:4])
    else:
        lines.append("- No strong cross-record patterns are obvious yet.")
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Progress",
    ])
    lines.extend(f"- {item}" for item in care_success_markers(profile, conflicts, inbox_files, review_queue))
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Metrics Being Tracked",
    ])
    tracked = {"weight"} | {item["metric"] for item in vital_entries}
    lines.append("- " + ", ".join(sorted(metric.replace("_", " ") for metric in tracked if metric)))
    lines.append("")
    return "\n".join(lines)


def _review_item_label(item: dict[str, Any]) -> str:
    """Format a review item's candidate into a bold, readable label."""
    candidate = item.get("candidate", {})
    section = item.get("section", "")
    if section == "recent_tests":
        name = candidate.get("name", "?")
        value = candidate.get("value", "?")
        unit = candidate.get("unit", "")
        return f"{name}: {value} {unit}".strip()
    if section == "medications":
        name = candidate.get("name", "?")
        dose = candidate.get("dose", "")
        return f"{name} {dose}".strip()
    if section == "conditions":
        return candidate.get("name", "?")
    if section == "allergies":
        return candidate.get("substance", "?")
    if section == "follow_up":
        return candidate.get("task", "?")
    return render_record(candidate, ("name", "value", "dose", "task"))


def render_review_worklist_text(review_queue: list[dict[str, Any]]) -> str:
    open_items = open_reviews(review_queue)
    tier_groups: dict[str, list[dict[str, Any]]] = {
        "safe_to_auto_apply": [],
        "needs_quick_confirmation": [],
        "do_not_trust_without_human_review": [],
    }
    for item in open_items:
        tier_groups.setdefault(item.get("tier", "needs_quick_confirmation"), []).append(item)

    lines = [
        "# Review Worklist",
        "",
        f"**{len(open_items)}** item(s) waiting for your review.",
        "",
    ]
    if not open_items:
        lines = [
            "# Review Worklist",
            "",
            "\u2705 Nothing is waiting for review right now. You're all caught up.",
            "",
        ]
        return "\n".join(lines)

    # Tier 1: Safe to accept
    safe = tier_groups.get("safe_to_auto_apply", [])
    if safe:
        lines.extend([
            _SECTION_DIVIDER,
            "",
            "## Items I'm Confident About",
            "",
            "These were extracted from your documents and look reliable. You can accept them all at once.",
            "",
        ])
        for idx, item in enumerate(safe, 1):
            label = _review_item_label(item)
            confidence = item.get("confidence", "high")
            source = item.get("source_title") or "unknown source"
            lines.append(f"{idx}. **{label}** (from \"{source}\", {confidence} confidence)")
            snippet = review_source_snippet(item)
            if snippet:
                lines.append(f"   Source line: \"{snippet}\"")
            lines.append(f"   \u2192 \u2610 Accept  \u2610 Skip")
            if item.get("applied"):
                lines.append("   *Already added to the record, but still worth a quick glance.*")
            lines.append("")

    # Tier 2: Needs confirmation
    medium = tier_groups.get("needs_quick_confirmation", [])
    if medium:
        lines.extend([
            _SECTION_DIVIDER,
            "",
            "## Items That Need Your Eye",
            "",
            "These were extracted but I'm less sure. Please check against the original document.",
            "",
        ])
        for idx, item in enumerate(medium, 1):
            label = _review_item_label(item)
            confidence = item.get("confidence", "medium")
            source = item.get("source_title") or "unknown source"
            lines.append(f"{idx}. **{label}** (from \"{source}\", {confidence} confidence)")
            snippet = review_source_snippet(item)
            if snippet:
                lines.append(f"   Source line: \"{snippet}\"")
            lines.append(f"   \u2192 \u2610 Accept  \u2610 Reject  \u2610 Not sure")
            lines.append("")

    # Tier 3: Do not trust
    cautious = tier_groups.get("do_not_trust_without_human_review", [])
    if cautious:
        lines.extend([
            _SECTION_DIVIDER,
            "",
            "## Items I Wouldn't Trust Without Checking",
            "",
            "These came from OCR or ambiguous text. Only accept if you can verify against the original.",
            "",
        ])
        for idx, item in enumerate(cautious, 1):
            label = _review_item_label(item)
            confidence = item.get("confidence", "low")
            source = item.get("source_title") or "unknown source"
            lines.append(f"{idx}. **{label}** (from \"{source}\", {confidence} confidence)")
            snippet = review_source_snippet(item)
            if snippet:
                lines.append(f"   Source line: \"{snippet}\"")
            lines.append(f"   \u2192 \u2610 Accept  \u2610 Reject  \u2610 Not sure")
            lines.append("")

    lines.append("")
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
    stale = staleness_warning(profile)
    open_review_items = open_reviews(review_queue)
    open_conflict_items = open_conflicts_only(conflicts)

    # Status bar
    inbox_chip = status_chip(not inbox_files, "Inbox clear", f"{len(inbox_files)} in inbox")
    review_chip = status_chip(not open_review_items, "Reviews done", f"{len(open_review_items)} to review")
    overdue_chip = status_chip(not due_now, "Nothing overdue", f"{len(due_now)} overdue")

    lines = [
        "# Today",
        "",
        f"{inbox_chip} | {review_chip} | {overdue_chip}",
        "",
        "You do not need to solve everything today. Focus on the smallest set of actions that keeps the record reliable and the next step clear.",
        "",
        _SECTION_DIVIDER,
        "",
        "## Focus Now",
    ]
    priorities = current_priorities(profile, conflicts, inbox_files, review_queue)
    if stale:
        priorities.append("Consider adding recent labs or visit notes.")
    lines.extend(f"- {item}" for item in priorities)
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Action Items",
    ])
    actionable = []
    if inbox_files:
        actionable.append(f"\u2610 Process inbox ({len(inbox_files)} waiting file(s))")
    if due_now:
        actionable.extend(
            f"\u2610 Follow up: {item.get('task')} (due {item.get('due_date') or 'no date'})"
            for item in due_now[:5]
        )
    if open_review_items:
        actionable.append(f"\u2610 Review {len(open_review_items)} extracted item(s)")
    if open_conflict_items:
        actionable.append(f"\u2610 Resolve {len(open_conflict_items)} source conflict(s)")
    if not actionable:
        actionable.append("\u2705 No urgent workspace maintenance is needed today.")
    lines.extend(f"- {item}" for item in actionable)
    lines.extend([
        "",
        _SECTION_DIVIDER,
        "",
        "## Quick Reassurance",
    ])
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


def _build_appointment_portal_message(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    next_item: dict[str, Any] | None,
) -> str:
    """Build a specific, conversational portal message for the appointment view."""
    task = next_item.get("task") if next_item else "my upcoming visit"
    parts: list[str] = [f"Hi, I'm writing about {task}."]
    # Include 1-2 concrete recent numbers in natural language
    abnormal = recent_abnormal_tests(profile, limit=2)
    if abnormal:
        for t in abnormal[:2]:
            name = t.get("name", "test")
            value = t.get("value", "?")
            unit = t.get("unit", "")
            flag = t.get("flag", "")
            flag_note = f", which was flagged {flag}" if flag else ""
            parts.append(f"My recent {name} was {value} {unit}{flag_note}.".strip())
    elif latest_recent_tests(profile, limit=1):
        t = latest_recent_tests(profile, limit=1)[0]
        parts.append(
            f"My most recent {t.get('name', 'test')} was {t.get('value', '?')} {t.get('unit', '')} on {t.get('date', '')}.".strip()
        )
    # Add a conversational question
    questions = suggested_visit_questions(profile)
    if questions:
        q = questions[0]
        # Make it first-person
        if q.startswith("What does"):
            q = "Should we discuss " + q[len("What does "):].rstrip("?") + "?"
        elif q.startswith("What should"):
            q = q  # already natural
        parts.append(q)
    return "- " + " ".join(parts)


def render_next_appointment_text(
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
) -> str:
    next_item = next_follow_up(profile)
    pattern_insights = build_pattern_insights(profile, medication_history, weight_entries, vital_entries)
    stale = staleness_warning(profile)
    lines = [
        "# Next Appointment",
        "",
    ]
    if stale:
        lines.append(f"> {stale}")
        lines.append("")
    lines.extend([
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
        _build_appointment_portal_message(profile, conflicts, review_queue, next_item),
    ])
    lines.extend([
        "",
        "## Current Medications",
        render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
        "",
        "## Most Relevant Recent Tests",
        render_list_with_trust(latest_recent_tests(profile, limit=5), ("name", "value", "unit", "flag", "date")),
        "",
        "## What To Bring Up In Plain Language",
    ])
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
    lines.extend(["", "## Pattern Connections Worth Mentioning"])
    if pattern_insights:
        lines.extend(f"- {item}" for item in pattern_insights[:4])
    else:
        lines.append("- No strong cross-record patterns are obvious yet.")
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


def _visit_reason_keywords(reason: str) -> set[str]:
    """Extract medical topic keywords from a visit reason string."""
    reason_lower = reason.lower()
    keyword_map: dict[str, list[str]] = {
        "lipid": ["ldl", "hdl", "triglycerides", "total cholesterol", "cholesterol"],
        "cholesterol": ["ldl", "hdl", "triglycerides", "total cholesterol", "cholesterol"],
        "thyroid": ["tsh", "t3", "t4", "free t4", "thyroid"],
        "cardiac": ["ldl", "hdl", "triglycerides", "blood pressure", "bnp", "troponin"],
        "heart": ["ldl", "hdl", "triglycerides", "blood pressure", "bnp", "troponin"],
        "diabetes": ["a1c", "glucose", "fasting glucose", "hba1c"],
        "blood sugar": ["a1c", "glucose", "fasting glucose", "hba1c"],
        "a1c": ["a1c", "glucose", "hba1c"],
        "blood pressure": ["blood pressure", "systolic", "diastolic"],
        "hypertension": ["blood pressure", "systolic", "diastolic", "bmp", "creatinine"],
        "kidney": ["creatinine", "bun", "gfr", "egfr"],
        "liver": ["alt", "ast", "bilirubin", "alkaline phosphatase"],
        "anemia": ["hemoglobin", "hematocrit", "iron", "ferritin", "cbc"],
    }
    matched: set[str] = set()
    for keyword, labs in keyword_map.items():
        if keyword in reason_lower:
            matched.update(labs)
    return matched


def _filter_tests_by_relevance(
    tests: list[dict[str, Any]], relevant_terms: set[str]
) -> list[dict[str, Any]]:
    """Filter tests to those relevant to visit reason. Keep all if no match."""
    if not relevant_terms:
        return tests
    filtered = [
        t for t in tests
        if any(term in normalize_test_name(str(t.get("name", ""))).lower() for term in relevant_terms)
    ]
    return filtered if filtered else tests


def _filter_conditions_by_relevance(
    conditions: list[dict[str, Any]], reason: str
) -> list[dict[str, Any]]:
    """Prioritize conditions relevant to the visit reason."""
    if not reason:
        return conditions
    reason_lower = reason.lower()
    relevant = [c for c in conditions if any(w in str(c.get("name", "")).lower() for w in reason_lower.split() if len(w) > 3)]
    other = [c for c in conditions if c not in relevant]
    return relevant + other


def render_clinician_packet_text(profile: dict[str, Any], visit_type: str, reason: str) -> str:
    stale = staleness_warning(profile)
    relevant_terms = _visit_reason_keywords(reason)
    all_tests = latest_recent_tests(profile, limit=10)
    relevant_tests = _filter_tests_by_relevance(all_tests, relevant_terms)[:6]
    prioritized_conditions = _filter_conditions_by_relevance(
        profile.get("conditions", []), reason
    )

    # Build key context section connecting reason to data
    key_context_lines: list[str] = []
    if relevant_terms:
        matching_abnormal = [
            t for t in relevant_tests
            if t.get("flag") in {"high", "low", "abnormal"}
        ]
        if matching_abnormal:
            for t in matching_abnormal[:3]:
                key_context_lines.append(
                    f"- {t.get('name')} was {t.get('value')} {t.get('unit', '')} ({t.get('flag')}) on {t.get('date', 'unknown')}"
                )
        relevant_meds = [
            m for m in profile.get("medications", [])
            if any(term in str(m.get("name", "")).lower() for term in relevant_terms)
            or any(term in reason.lower() for term in str(m.get("name", "")).lower().split() if len(term) > 3)
        ]
        if relevant_meds:
            key_context_lines.append(
                "- Related medications: " + ", ".join(
                    f"{m.get('name')} {m.get('dose', '')}".strip() for m in relevant_meds[:3]
                )
            )
        related_follow_ups = [
            f for f in pending_follow_ups(profile)
            if any(term in str(f.get("task", "")).lower() for term in relevant_terms)
        ]
        if related_follow_ups:
            for fu in related_follow_ups[:2]:
                key_context_lines.append(f"- Open follow-up: {fu.get('task')} (due {fu.get('due_date', 'unknown')})")
    if not key_context_lines:
        key_context_lines.append(f"- Visit focus: {reason or visit_type or 'general review'}")

    # Dynamic heading based on profile content
    heading = "Clinician Packet"
    if relevant_terms:
        heading = f"Clinician Packet — {reason.title()}" if reason else heading

    lines = [
        f"# {heading}",
        "",
    ]
    if stale:
        lines.append(f"> {stale}")
        lines.append("")
    lines.extend([
        f"- Patient: {profile.get('name') or profile.get('person_id') or 'unknown'}",
        f"- Visit type: {visit_type}",
        f"- Main reason: {reason}",
        "",
        "## Key Context For This Visit",
    ])
    lines.extend(key_context_lines)
    lines.extend([
        "",
        "## 30-Second Summary",
        f"- {thirty_second_summary(profile, [], [])}",
        "",
        "## Conditions",
        render_list_with_trust(prioritized_conditions, ("name", "status")),
        "",
        "## Current Medications",
        render_list_with_trust(profile.get("medications", []), ("name", "dose", "form", "frequency", "status")),
        "",
        "## Allergies",
        render_list_with_trust(profile.get("allergies", []), ("substance", "reaction", "severity")),
        "",
        "## Recent Tests",
        render_list_with_trust(relevant_tests, ("name", "value", "unit", "flag", "date")),
        "",
        "## Follow Up And Questions",
        render_list_with_trust(profile.get("follow_up", []), ("task", "due_date", "status")),
        "",
        "## Questions To Discuss",
        "\n".join(f"- {item}" for item in suggested_visit_questions(profile)),
        "",
    ])

    # Safety Alerts: medication-allergy cross-validation (#Item 2)
    safety_alerts = check_medication_allergy_conflicts(profile)
    if safety_alerts:
        lines.extend([
            "## Safety Alerts",
        ])
        for alert in safety_alerts:
            lines.append(
                f"- **{alert['risk'].upper()} RISK**: {alert['medication']} vs allergy "
                f"'{alert['allergy']}' — {alert['reason']}"
            )
        lines.append("")

    return "\n".join(lines)


def render_portal_message_text(profile: dict[str, Any], message_goal: str) -> str:
    # Pick 1-2 most relevant recent numbers
    abnormal = recent_abnormal_tests(profile, limit=3)
    latest = latest_recent_tests(profile, limit=2)

    # Build specific, conversational number references
    number_parts: list[str] = []
    if abnormal:
        for t in abnormal[:2]:
            name = t.get("name", "test")
            value = t.get("value", "?")
            unit = t.get("unit", "")
            flag = t.get("flag", "")
            flag_note = f", which was flagged {flag}" if flag else ""
            number_parts.append(f"my recent {name} was {value} {unit}{flag_note}".strip())
    elif latest:
        t = latest[0]
        number_parts.append(
            f"my most recent {t.get('name', 'test')} was {t.get('value', '?')} {t.get('unit', '')} on {t.get('date', '')}".strip()
        )

    # Pick the single most important question and make it conversational
    questions = suggested_visit_questions(profile)
    top_question = questions[0] if questions else "What should I watch for before the next visit?"
    # Convert question to first-person if it starts with "What does..."
    if top_question.startswith("What does"):
        top_question = top_question.replace("What does the recent", "I'd like to understand what my recent")

    # Build a natural, first-person message under 80 words
    parts: list[str] = [f"Hi, I'm writing about {message_goal}."]
    if number_parts:
        parts.append(f"For context, {'; '.join(number_parts)}.")
    parts.append(top_question)

    message_body = " ".join(parts)

    lines = [
        "# Portal Message Draft",
        "",
        message_body,
        "",
    ]
    return "\n".join(lines)


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
    stale = staleness_warning(profile)
    sections = [
        "# Health Dossier",
        "",
    ]
    if stale:
        sections.append(f"> {stale}")
        sections.append("")
    sections.extend([
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
    ])
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
    snap = load_snapshot(root, person_id)
    profile = snap.profile
    conflicts = snap.conflicts
    review_queue = snap.review_queue
    medication_history = snap.medication_history
    weight_entries = snap.weight_entries
    vital_entries = snap.vital_entries
    inbox_files = snap.inbox_files

    sync_conflict_count_from(conflicts, profile)
    sync_review_count_from(review_queue, profile)
    save_profile(root, person_id, profile)

    summary = render_summary_text(profile, conflicts, inbox_files, review_queue, weight_entries)
    atomic_write_text(summary_path(root, person_id), summary)
    atomic_write_text(
        home_path(root, person_id),
        render_health_home_text(
            profile,
            conflicts,
            inbox_files,
            review_queue,
            weight_entries,
            vital_entries,
            medication_history,
        ),
    )
    session_changes = changes_since_last_session(root, person_id)
    atomic_write_text(
        start_here_path(root, person_id),
        render_start_here_text(
            profile,
            inbox_files=inbox_files,
            review_queue=review_queue,
            conflicts=conflicts,
            session_changes=session_changes,
        ),
    )
    mark_session(root, person_id)
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
        render_next_appointment_text(
            profile,
            conflicts,
            review_queue,
            medication_history,
            weight_entries,
            vital_entries,
        ),
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
    atomic_write_text(
        patterns_path(root, person_id),
        render_patterns_text(profile, medication_history, weight_entries, vital_entries),
    )
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

    # Generate HTML artifact (default alongside markdown)
    try:
        from .artifacts import generate_health_home_artifact
    except ImportError:
        try:
            from artifacts import generate_health_home_artifact
        except ImportError:
            generate_health_home_artifact = None  # type: ignore[assignment]
    if generate_health_home_artifact is not None:
        try:
            generate_health_home_artifact(root, person_id)
        except Exception:
            pass  # HTML generation is best-effort, never blocks markdown

    return summary_path(root, person_id), dossier_path(root, person_id)


# ---------------------------------------------------------------------------
# Query-relevant dashboard (#new)
# ---------------------------------------------------------------------------

# Intent categories for classifying user queries.
QUERY_INTENTS: dict[str, dict[str, Any]] = {
    "lab_review": {
        "keywords": [
            "lab", "labs", "test", "tests", "result", "results", "blood work",
            "bloodwork", "panel", "cbc", "lipid", "a1c", "tsh", "cholesterol",
            "ldl", "hdl", "bun", "creatinine", "hemoglobin", "glucose",
        ],
        "title": "Lab Review Dashboard",
        "sections": ["identity", "staleness", "relevant_labs", "lab_trends",
                      "abnormal_flags", "patterns", "questions"],
    },
    "medication_review": {
        "keywords": [
            "medication", "medications", "med", "meds", "drug", "drugs",
            "prescription", "prescriptions", "dose", "dosage", "side effect",
            "interaction", "refill", "pharmacy", "statin", "metformin",
            "insulin", "lisinopril", "worried", "concerned", "too many",
            "pills", "interactions", "reconciliation", "reconcile",
        ],
        "title": "Medication Review Dashboard",
        "sections": ["identity", "staleness", "medications", "medication_history",
                      "medication_conflicts", "allergies", "related_labs", "questions"],
    },
    "visit_prep": {
        "keywords": [
            "appointment", "visit", "doctor", "pcp", "specialist", "telehealth",
            "urgent care", "prepare", "prep", "bring", "ask", "questions",
            "next visit", "upcoming",
        ],
        "title": "Visit Prep Dashboard",
        "sections": ["identity", "staleness", "thirty_second", "next_followup",
                      "medications", "relevant_labs", "recent_changes", "patterns",
                      "portal_message", "questions"],
    },
    "symptom_triage": {
        "keywords": [
            "symptom", "symptoms", "pain", "hurts", "ache", "fever", "nausea",
            "dizzy", "tired", "fatigue", "swelling", "rash", "breathing",
            "cough", "headache", "worry", "worried", "should i",
            "concerned", "risk",
        ],
        "title": "Symptom Context Dashboard",
        "sections": ["identity", "staleness", "conditions", "medications",
                      "allergies", "recent_encounters", "relevant_labs",
                      "vitals_snapshot", "questions"],
    },
    "weight_vitals": {
        "keywords": [
            "weight", "bmi", "blood pressure", "bp", "heart rate", "pulse",
            "glucose", "sugar", "vitals", "trend", "tracking",
            "gain", "loss", "fluctuations",
        ],
        "title": "Vitals Dashboard",
        "sections": ["identity", "staleness", "weight_trend", "vitals_trend",
                      "bp_insights", "patterns", "questions"],
    },
    "caregiver_overview": {
        "keywords": [
            "overview", "summary", "status", "everything", "catch up",
            "what's going on", "update", "how is", "caregiver",
        ],
        "title": "Health Overview Dashboard",
        "sections": ["identity", "staleness", "thirty_second", "priorities",
                      "conditions", "medications", "abnormal_flags",
                      "next_followup", "inbox_status", "patterns", "questions"],
    },
    "follow_up": {
        "keywords": [
            "follow up", "follow-up", "followup", "overdue", "due",
            "schedule", "next step", "pending", "todo", "action",
        ],
        "title": "Follow-Up Dashboard",
        "sections": ["identity", "staleness", "overdue_items", "upcoming_items",
                      "inbox_status", "review_queue_summary", "conflicts_summary",
                      "questions"],
    },
    "medication_reconciliation": {
        "keywords": [
            "reconciliation", "reconcile", "compare", "old list", "new list",
            "medication changes", "switched",
        ],
        "title": "Medication Reconciliation Dashboard",
        "sections": ["identity", "staleness", "medications", "medication_history",
                      "medication_conflicts", "related_labs", "questions"],
    },
    "side_effect_check": {
        "keywords": [
            "side effect", "side effects", "adverse", "reaction",
            "since starting", "after taking", "muscle pain", "nausea from",
        ],
        "title": "Side Effect Safety Dashboard",
        "sections": ["identity", "staleness", "medications", "allergies",
                      "recent_encounters", "patterns", "questions"],
    },
}


def classify_query_intent(query: str) -> str:
    """Classify a user query into the single best intent category.

    Returns the best-matching intent key, or 'caregiver_overview' as default.
    """
    intents = classify_query_intents(query, max_intents=1)
    return intents[0] if intents else "caregiver_overview"


def classify_query_intents(query: str, max_intents: int = 2) -> list[str]:
    """Classify a user query into one or more intent categories (multi-intent).

    Returns up to max_intents matching intents, sorted by score descending.
    Supports compound queries like "what are my labs and when is my next appointment".
    """
    query_lower = query.lower()
    scores: dict[str, int] = {}
    for intent_key, intent_data in QUERY_INTENTS.items():
        score = sum(1 for kw in intent_data["keywords"] if kw in query_lower)
        if score > 0:
            scores[intent_key] = score
    if not scores:
        return ["caregiver_overview"]
    ranked = sorted(scores, key=scores.get, reverse=True)
    # Only include secondary intents if they have meaningful overlap (score > 1)
    result = [ranked[0]]
    for intent in ranked[1:max_intents]:
        if scores[intent] >= 2:
            result.append(intent)
    return result


def detect_person_in_query(query: str, known_names: list[str]) -> str | None:
    """Detect if a query mentions a known person name (caregiver mode).

    Returns the matched person folder name, or None.
    """
    query_lower = query.lower()
    for name in known_names:
        # Match first name, full name, or folder name
        name_lower = name.lower()
        parts = name_lower.split()
        if name_lower in query_lower:
            return name
        if parts and parts[0] in query_lower and len(parts[0]) > 2:
            return name
    return None


def _render_dashboard_section(
    section: str,
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
    inbox_files: list[Path],
    query: str = "",
) -> list[str]:
    """Render a single dashboard section. Returns lines."""
    lines: list[str] = []

    if section == "identity":
        lines.extend([
            "## Person",
            f"- {profile.get('name') or 'unknown'}",
            f"- DOB: {profile.get('date_of_birth') or 'unknown'} | Sex: {profile.get('sex') or 'unknown'}",
            f"- Last updated: {profile.get('audit', {}).get('updated_at') or 'unknown'}",
            "",
        ])

    elif section == "staleness":
        stale = staleness_warning(profile)
        if stale:
            lines.extend([f"> {stale}", ""])

    elif section == "thirty_second":
        lines.extend([
            "## At A Glance",
            f"- {thirty_second_summary(profile, conflicts, review_queue)}",
            "",
        ])

    elif section == "priorities":
        lines.extend(["## Priorities"])
        for item in current_priorities(profile, conflicts, inbox_files, review_queue):
            lines.append(f"- {item}")
        lines.append("")

    elif section == "conditions":
        lines.extend([
            "## Known Conditions",
            render_list_with_trust(profile.get("conditions", []), ("name", "status")),
            "",
        ])

    elif section == "medications":
        lines.extend([
            "## Current Medications",
            render_list_with_trust(
                profile.get("medications", []),
                ("name", "dose", "form", "frequency", "status"),
            ),
            "",
        ])

    elif section == "allergies":
        lines.extend([
            "## Allergies",
            render_list_with_trust(
                profile.get("allergies", []),
                ("substance", "reaction", "severity"),
            ),
            "",
        ])

    elif section == "relevant_labs":
        relevant_terms = _visit_reason_keywords(query)
        all_tests = latest_recent_tests(profile, limit=10)
        filtered = _filter_tests_by_relevance(all_tests, relevant_terms)[:8]
        lines.extend([
            "## Relevant Lab Results",
            render_list_with_trust(
                filtered,
                ("name", "value", "unit", "flag", "date", "reference_range"),
            ),
            "",
        ])

    elif section == "lab_trends":
        lines.append(render_trends_text(profile))

    elif section == "abnormal_flags":
        abnormal = recent_abnormal_tests(profile, limit=5)
        if abnormal:
            lines.extend(["## Abnormal Flags"])
            for item in abnormal:
                lines.append(
                    f"- {item.get('name')} {item.get('value')} {item.get('unit', '')} "
                    f"({item.get('flag')}) on {item.get('date', 'unknown')}"
                )
            lines.append("")

    elif section == "patterns":
        insights = build_pattern_insights(
            profile, medication_history, weight_entries, vital_entries
        )
        if insights:
            lines.extend(["## Pattern Signals"])
            lines.extend(f"- {item}" for item in insights)
            lines.append("")

    elif section == "medication_history":
        if medication_history:
            lines.extend(["## Recent Medication Changes"])
            for item in medication_history[-5:]:
                lines.append(
                    f"- {item.get('recorded_at', '?')[:10]} | "
                    f"{item.get('event_type')} | {item.get('medication_name')}"
                )
            lines.append("")

    elif section == "medication_conflicts":
        med_conflicts = [
            c for c in conflicts
            if c.get("section") == "medications" and c.get("status") == "open"
        ]
        if med_conflicts:
            lines.extend(["## Open Medication Conflicts"])
            for item in med_conflicts:
                lines.append(
                    f"- {item['identity']} field `{item['field']}`: "
                    f"'{item['previous']}' vs '{item['new_value']}'"
                )
            lines.append("")

    elif section == "related_labs":
        # Labs related to current medications
        med_names = {
            str(m.get("name", "")).lower() for m in profile.get("medications", [])
        }
        relevant: set[str] = set()
        statin_names = {"atorvastatin", "rosuvastatin", "simvastatin", "pravastatin"}
        if med_names & statin_names:
            relevant.update(["ldl", "hdl", "triglycerides", "total cholesterol"])
        if "metformin" in med_names:
            relevant.update(["a1c", "glucose"])
        if "levothyroxine" in med_names:
            relevant.add("tsh")
        tests = _filter_tests_by_relevance(
            latest_recent_tests(profile, limit=10), relevant
        )[:5]
        if tests:
            lines.extend([
                "## Labs Related To Current Medications",
                render_list_with_trust(
                    tests,
                    ("name", "value", "unit", "flag", "date"),
                ),
                "",
            ])

    elif section == "next_followup":
        nf = next_follow_up(profile)
        if nf:
            lines.extend([
                "## Next Follow-Up",
                f"- {render_record(nf, ('task', 'due_date', 'status'))}",
                "",
            ])

    elif section == "recent_changes":
        abnormal = recent_abnormal_tests(profile, limit=3)
        oq = open_reviews(review_queue)
        oc = open_conflicts_only(conflicts)
        lines.extend(["## What Changed Recently"])
        if abnormal:
            lines.append(
                "- Recent abnormal labs: " +
                ", ".join(
                    f"{i.get('name')} {i.get('value')} {i.get('unit', '')}".strip()
                    for i in abnormal
                )
            )
        if oq:
            lines.append(f"- {len(oq)} extracted item(s) still need confirmation")
        if oc:
            lines.append(f"- {len(oc)} source conflict(s) remain open")
        if not abnormal and not oq and not oc:
            lines.append("- No major recent changes on record")
        lines.append("")

    elif section == "portal_message":
        nf = next_follow_up(profile)
        goal = nf.get("task", "follow-up") if nf else "follow-up"
        lines.extend([
            "## Quick Portal Message Draft",
            render_portal_message_text(profile, goal).split("\n", 4)[-1]
            if "\n" in render_portal_message_text(profile, goal) else "",
            "",
        ])

    elif section == "weight_trend":
        lines.append(render_weight_trends_text(weight_entries))

    elif section == "vitals_trend":
        lines.append(render_vitals_trends_text(vital_entries))

    elif section == "bp_insights":
        bp_entries = [e for e in vital_entries if e.get("metric") == "blood_pressure"]
        if bp_entries:
            latest = bp_entries[-1]
            lines.extend([
                "## Latest Blood Pressure",
                f"- {latest.get('value_text')} {latest.get('unit', '')} on {latest.get('entry_date', 'unknown')}",
            ])
            elevated = sum(
                1 for e in bp_entries
                if (e.get("systolic") or 0) >= 130 or (e.get("diastolic") or 0) >= 80
            )
            if elevated:
                lines.append(f"- Elevated in {elevated} of {len(bp_entries)} recorded entries")
            lines.append("")

    elif section == "recent_encounters":
        encounters = profile.get("encounters", [])[-5:]
        if encounters:
            lines.extend(["## Recent Encounters"])
            for e in reversed(encounters):
                lines.append(
                    f"- {e.get('date', '?')} | {e.get('kind', '?')} | "
                    f"{e.get('title', '?')}"
                )
            lines.append("")

    elif section == "vitals_snapshot":
        if vital_entries:
            # Show latest of each metric
            by_metric: dict[str, dict[str, Any]] = {}
            for e in vital_entries:
                by_metric[e["metric"]] = e
            lines.extend(["## Latest Vitals"])
            for metric, entry in sorted(by_metric.items()):
                lines.append(
                    f"- {metric}: {entry.get('value_text')} "
                    f"{entry.get('unit', '')} ({entry.get('entry_date', '?')})"
                )
            lines.append("")

    elif section == "overdue_items":
        overdue = due_follow_ups(profile, days=0)
        lines.extend(["## Overdue"])
        if overdue:
            for item in overdue[:8]:
                lines.append(
                    f"- {item.get('task')} | due {item.get('due_date', '?')} | "
                    f"{item.get('status', '?')}"
                )
        else:
            lines.append("- Nothing overdue right now")
        lines.append("")

    elif section == "upcoming_items":
        upcoming = due_follow_ups(profile, days=14)
        overdue_set = {id(i) for i in due_follow_ups(profile, days=0)}
        upcoming_only = [i for i in upcoming if id(i) not in overdue_set]
        lines.extend(["## Coming Up (next 14 days)"])
        if upcoming_only:
            for item in upcoming_only[:8]:
                lines.append(
                    f"- {item.get('task')} | due {item.get('due_date', '?')}"
                )
        else:
            lines.append("- No dated items in the next 14 days")
        lines.append("")

    elif section == "inbox_status":
        lines.extend([
            "## Inbox",
            f"- {len(inbox_files)} file(s) waiting" if inbox_files else "- Inbox is clear",
            "",
        ])

    elif section == "review_queue_summary":
        open_items = open_reviews(review_queue)
        lines.extend([
            "## Review Queue",
            f"- {len(open_items)} item(s) need confirmation" if open_items
            else "- No items waiting for review",
            "",
        ])

    elif section == "conflicts_summary":
        oc = open_conflicts_only(conflicts)
        lines.extend([
            "## Open Conflicts",
            f"- {len(oc)} conflict(s) need resolution" if oc
            else "- No conflicts open",
            "",
        ])

    elif section == "questions":
        questions = suggested_visit_questions(profile)
        lines.extend(["## Suggested Questions"])
        lines.extend(f"- {q}" for q in questions[:4])
        lines.append("")

    return lines


@dataclasses.dataclass
class DashboardResult:
    """Result from dashboard generation, including metadata for caching."""

    text: str
    query: str
    primary_intent: str
    intents_used: list[str]
    from_cache: bool = False
    cache_query: str = ""  # original query if served from cache


def _merge_sections_for_intents(intents: list[str]) -> list[str]:
    """Merge section lists from multiple intents, preserving order and deduplicating."""
    seen: set[str] = set()
    merged: list[str] = []
    for intent_key in intents:
        intent_data = QUERY_INTENTS.get(intent_key, {})
        for section in intent_data.get("sections", []):
            if section not in seen:
                seen.add(section)
                merged.append(section)
    return merged


def render_query_dashboard(
    query: str,
    profile: dict[str, Any],
    conflicts: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    medication_history: list[dict[str, Any]],
    weight_entries: list[dict[str, Any]],
    vital_entries: list[dict[str, Any]],
    inbox_files: list[Path],
) -> DashboardResult:
    """Build a dashboard focused on the user's query.

    Supports multi-intent queries (e.g., "labs and next appointment").
    Returns a DashboardResult with text and metadata for caching.
    """
    intents = classify_query_intents(query, max_intents=2)
    primary = intents[0]
    primary_data = QUERY_INTENTS[primary]

    # Build title
    if len(intents) > 1:
        titles = [QUERY_INTENTS[i]["title"] for i in intents]
        title = " + ".join(titles)
    else:
        title = primary_data["title"]

    # Merge sections from all matched intents
    sections = _merge_sections_for_intents(intents)

    lines = [
        f"# {title}",
        "",
        f"*Focused on: {query}*",
        "",
    ]

    for section in sections:
        section_lines = _render_dashboard_section(
            section,
            profile,
            conflicts,
            review_queue,
            medication_history,
            weight_entries,
            vital_entries,
            inbox_files,
            query=query,
        )
        lines.extend(section_lines)

    lines.extend([
        "---",
        f"*Dashboard generated {date.today().isoformat()} | "
        f"intent: {'+'.join(intents)} | "
        f"query: \"{query}\"*",
        "",
    ])

    return DashboardResult(
        text="\n".join(lines),
        query=query,
        primary_intent=primary,
        intents_used=intents,
    )


def render_query_dashboard_from_snapshot(
    query: str,
    snap: WorkspaceSnapshot,
) -> DashboardResult:
    """Convenience wrapper that unpacks a WorkspaceSnapshot."""
    return render_query_dashboard(
        query=query,
        profile=snap.profile,
        conflicts=snap.conflicts,
        review_queue=snap.review_queue,
        medication_history=snap.medication_history,
        weight_entries=snap.weight_entries,
        vital_entries=snap.vital_entries,
        inbox_files=snap.inbox_files,
    )
