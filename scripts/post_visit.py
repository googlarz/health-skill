#!/usr/bin/env python3
"""Post-visit note processor for Health Skill.

After an appointment, the user can paste or describe what happened.
This module extracts structured data and merges it into the health profile.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

_NEW_DIAGNOSIS_PATTERNS = [
    r"diagnosed (?:with )?(.+?)(?:\.|,|;|$)",
    r"new diagnosis[:\s]+(.+?)(?:\.|,|;|$)",
    r"impression[:\s]+(.+?)(?:\.|,|;|$)",
]

_NEW_MED_PATTERNS = [
    r"(?:starting|start|prescri(?:bed|bing)|added?) (.+?)(?:\s+\d+\s*mg|\s+\d+\s*mcg|\s+\d+\s*iu|\.|\,|$)",
    r"new (?:medication|prescription|rx)[:\s]+(.+?)(?:\.|,|$)",
]

_STOPPED_MED_PATTERNS = [
    r"(?:stop(?:ping)?|discontinu(?:e|ing)|d/c) (.+?)(?:\.|,|;|$)",
    r"stop (.+?) due",
]

_LAB_ORDER_PATTERNS = [
    r"(?:order(?:ed)?|check|recheck|repeat|schedule)\s+(.+?)\s+(?:lab|blood|test|panel|screen)",
    r"labs? ordered[:\s]+(.+?)(?:\.|,|$)",
]

_FOLLOW_UP_PATTERNS = [
    r"follow[- ]?up\s+(?:in\s+)?(\d+\s+(?:week|month|day)s?)",
    r"return\s+(?:in\s+)?(\d+\s+(?:week|month|day)s?)",
    r"see (?:me|you|them) (?:back )?in (\d+\s+(?:week|month|day)s?)",
]

_REFERRAL_PATTERNS = [
    r"refer(?:red|ring)? to (.+?)(?:\.|,|;|$)",
    r"referral to (.+?)(?:\.|,|;|$)",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_visit_data(notes_text: str) -> dict[str, Any]:
    """Parse free-text visit notes into structured fields.

    Returns dict with keys: new_conditions, new_medications, stopped_medications,
    labs_ordered, follow_up_interval, referrals, raw.
    """
    text = notes_text.lower()

    return {
        "new_conditions": _extract_all(_NEW_DIAGNOSIS_PATTERNS, text),
        "new_medications": _extract_all(_NEW_MED_PATTERNS, text),
        "stopped_medications": _extract_all(_STOPPED_MED_PATTERNS, text),
        "labs_ordered": _extract_all(_LAB_ORDER_PATTERNS, text),
        "follow_up_interval": _extract_first(_FOLLOW_UP_PATTERNS, text),
        "referrals": _extract_all(_REFERRAL_PATTERNS, text),
        "raw": notes_text.strip(),
    }


def merge_visit_data(profile: dict[str, Any], visit_data: dict[str, Any],
                     visit_date: str | None = None) -> dict[str, int]:
    """Merge extracted visit data into the health profile. Returns counts of changes."""
    counts: dict[str, int] = {}
    today = visit_date or date.today().isoformat()

    # Add new conditions
    existing_conditions = {c["name"].lower() for c in profile.get("conditions", [])}
    added_conditions = 0
    for name in visit_data.get("new_conditions", []):
        clean = name.strip().rstrip(".")
        if clean and clean.lower() not in existing_conditions:
            profile.setdefault("conditions", []).append({
                "name": clean,
                "diagnosed": today,
                "source": "visit_notes",
            })
            existing_conditions.add(clean.lower())
            added_conditions += 1
    if added_conditions:
        counts["conditions"] = added_conditions

    # Add new medications
    existing_meds = {m["name"].lower() for m in profile.get("medications", [])}
    added_meds = 0
    for name in visit_data.get("new_medications", []):
        clean = name.strip().rstrip(".")
        if clean and clean.lower() not in existing_meds:
            profile.setdefault("medications", []).append({
                "name": clean,
                "start_date": today,
                "source": "visit_notes",
            })
            existing_meds.add(clean.lower())
            added_meds += 1
    if added_meds:
        counts["medications_added"] = added_meds

    # Mark stopped medications as inactive
    stopped = 0
    for name in visit_data.get("stopped_medications", []):
        clean = name.strip().lower()
        for med in profile.get("medications", []):
            if clean in med["name"].lower() and med.get("active", True):
                med["active"] = False
                med["end_date"] = today
                stopped += 1
    if stopped:
        counts["medications_stopped"] = stopped

    # Store visit record
    visit_record = {
        "date": today,
        "raw_notes": visit_data.get("raw", ""),
        "follow_up": visit_data.get("follow_up_interval"),
        "labs_ordered": visit_data.get("labs_ordered", []),
        "referrals": visit_data.get("referrals", []),
    }
    profile.setdefault("visit_history", []).append(visit_record)
    counts["visits"] = 1

    return counts


def write_post_visit_summary(profile: dict[str, Any], visit_data: dict[str, Any],
                              visit_date: str | None = None) -> str:
    """Render a human-readable post-visit summary."""
    lines: list[str] = []
    today = visit_date or date.today().isoformat()

    lines.append(f"# Post-Visit Summary — {today}")
    lines.append("")

    new_conditions = visit_data.get("new_conditions", [])
    if new_conditions:
        lines.append("## New Diagnoses")
        for c in new_conditions:
            lines.append(f"- {c.strip().rstrip('.')}")
        lines.append("")

    new_meds = visit_data.get("new_medications", [])
    if new_meds:
        lines.append("## New Medications Started")
        for m in new_meds:
            lines.append(f"- {m.strip().rstrip('.')}")
        lines.append("")

    stopped_meds = visit_data.get("stopped_medications", [])
    if stopped_meds:
        lines.append("## Medications Stopped")
        for m in stopped_meds:
            lines.append(f"- {m.strip().rstrip('.')}")
        lines.append("")

    labs = visit_data.get("labs_ordered", [])
    if labs:
        lines.append("## Labs Ordered")
        for lab in labs:
            lines.append(f"- {lab.strip().rstrip('.')}")
        lines.append("")

    referrals = visit_data.get("referrals", [])
    if referrals:
        lines.append("## Referrals")
        for r in referrals:
            lines.append(f"- {r.strip().rstrip('.')}")
        lines.append("")

    follow_up = visit_data.get("follow_up_interval")
    if follow_up:
        lines.append(f"## Follow-Up")
        lines.append(f"Return in {follow_up}.")
        lines.append("")

    if not any([new_conditions, new_meds, stopped_meds, labs, referrals, follow_up]):
        lines.append("No structured data extracted. Raw notes saved to visit history.")
        lines.append("")

    raw = visit_data.get("raw", "")
    if raw:
        lines.append("## Full Notes")
        lines.append(raw)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_all(patterns: list[str], text: str) -> list[str]:
    results = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            val = match.group(1).strip()
            if val and val not in seen and len(val) > 2:
                results.append(val)
                seen.add(val)
    return results


def _extract_first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None
