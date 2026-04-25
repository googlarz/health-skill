#!/usr/bin/env python3
"""Appointment management for Health Skill.

Features:
- Upcoming appointment detection from profile
- Pre-visit brief generation (relevant history, recent labs, questions to ask)
- Post-visit follow-up tracking
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Pre-visit brief
# ---------------------------------------------------------------------------

def build_pre_visit_brief(profile: dict[str, Any], appointment: dict[str, Any]) -> str:
    """Generate a structured pre-visit brief for an upcoming appointment."""
    lines: list[str] = []
    spec = appointment.get("specialty", "").lower()
    reason = appointment.get("reason", "")
    appt_date = appointment.get("date", "")

    lines.append(f"# Pre-Visit Brief")
    if appt_date:
        lines.append(f"**Date:** {appt_date}")
    if spec:
        lines.append(f"**Specialty:** {spec.title()}")
    if reason:
        lines.append(f"**Reason:** {reason}")
    lines.append("")

    # Relevant conditions
    conditions = profile.get("conditions", [])
    if conditions:
        lines.append("## Active Conditions")
        for c in conditions:
            lines.append(f"- {c['name']}")
        lines.append("")

    # Relevant medications
    meds = profile.get("medications", [])
    if meds:
        lines.append("## Current Medications")
        for m in meds:
            dose = m.get("dose", "")
            freq = m.get("frequency", "")
            detail = f" — {dose}" if dose else ""
            detail += f", {freq}" if freq else ""
            lines.append(f"- {m['name']}{detail}")
        lines.append("")

    # Allergies
    allergies = profile.get("allergies", [])
    if allergies:
        lines.append("## Allergies")
        for a in allergies:
            reaction = a.get("reaction", "")
            lines.append(f"- {a['name']}" + (f" ({reaction})" if reaction else ""))
        lines.append("")

    # Recent labs (last 12 months)
    labs = _recent_labs(profile, months=12)
    if labs:
        lines.append("## Recent Lab Results")
        for lab in labs[:8]:
            lines.append(f"- {lab['marker']}: {lab['value']} {lab.get('unit', '')} ({lab['date']})")
        lines.append("")

    # Recent check-in trends (last 7 days)
    trend = _recent_checkin_summary(profile, days=7)
    if trend:
        lines.append("## Recent Health Trends (7 days)")
        lines.append(trend)
        lines.append("")

    # Specialty-specific questions
    questions = _suggested_questions(profile, spec, reason)
    if questions:
        lines.append("## Suggested Questions to Ask")
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    # Outstanding concerns
    concerns = _outstanding_concerns(profile)
    if concerns:
        lines.append("## Things to Mention")
        for c in concerns:
            lines.append(f"- {c}")
        lines.append("")

    lines.append("---")
    lines.append("*Bring this summary and your insurance card. Arrive 10 minutes early.*")
    return "\n".join(lines)


def get_upcoming_appointments(profile: dict[str, Any], days_ahead: int = 30) -> list[dict[str, Any]]:
    """Return appointments in the next `days_ahead` days, sorted by date."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    upcoming = []
    for appt in profile.get("appointments", []):
        try:
            d = date.fromisoformat(appt["date"])
            if today <= d <= cutoff:
                upcoming.append(appt)
        except (KeyError, ValueError):
            continue
    return sorted(upcoming, key=lambda a: a["date"])


def write_appointment_alerts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return alert dicts for appointments in the next 7 days."""
    alerts = []
    upcoming = get_upcoming_appointments(profile, days_ahead=7)
    for appt in upcoming:
        d = date.fromisoformat(appt["date"])
        days_until = (d - date.today()).days
        spec = appt.get("specialty", "appointment")
        reason = appt.get("reason", "")
        msg = f"Upcoming {spec}"
        if reason:
            msg += f" ({reason})"
        if days_until == 0:
            msg += " — TODAY"
        elif days_until == 1:
            msg += " — tomorrow"
        else:
            msg += f" — in {days_until} days"
        alerts.append({
            "type": "appointment",
            "message": msg,
            "date": appt["date"],
            "priority": "high" if days_until <= 1 else "medium",
        })
    return alerts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recent_labs(profile: dict[str, Any], months: int = 12) -> list[dict[str, Any]]:
    cutoff = (date.today() - timedelta(days=months * 30)).isoformat()
    labs = []
    for entry in profile.get("lab_results", []):
        if entry.get("date", "") >= cutoff:
            labs.append(entry)
    return sorted(labs, key=lambda x: x.get("date", ""), reverse=True)


def _recent_checkin_summary(profile: dict[str, Any], days: int = 7) -> str:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    checkins = [c for c in profile.get("daily_checkins", []) if c.get("date", "") >= cutoff]
    if not checkins:
        return ""
    avg = lambda key: sum(c.get(key, 0) for c in checkins) / len(checkins)
    mood = avg("mood")
    energy = avg("energy")
    pain = avg("pain")
    sleep = avg("sleep_hours")
    parts = []
    if mood:
        parts.append(f"Mood avg {mood:.1f}/10")
    if energy:
        parts.append(f"energy avg {energy:.1f}/10")
    if pain:
        parts.append(f"pain avg {pain:.1f}/10")
    if sleep:
        parts.append(f"sleep avg {sleep:.1f}h")
    return ", ".join(parts) if parts else ""


def _suggested_questions(profile: dict[str, Any], spec: str, reason: str) -> list[str]:
    questions: list[str] = []
    conditions = [c["name"].lower() for c in profile.get("conditions", [])]
    meds = [m["name"].lower() for m in profile.get("medications", [])]

    # Generic questions always useful
    questions.append("What are the most important things I should be doing between now and my next visit?")

    # Specialty-specific
    if "cardio" in spec:
        questions.append("Should I have a stress test or echocardiogram this year?")
        questions.append("What is my current 10-year cardiovascular risk?")
        if any("hypertension" in c or "blood pressure" in c for c in conditions):
            questions.append("Is my current BP target appropriate given my other conditions?")

    elif "endocrin" in spec or "thyroid" in spec or "diabetes" in spec:
        if any("diabetes" in c for c in conditions):
            questions.append("What is my current HbA1c target?")
            questions.append("Should I be screened for diabetic complications (retinopathy, nephropathy)?")
        if any("thyroid" in c or "hypothyroid" in c for c in conditions):
            questions.append("What TSH range are you targeting for me specifically?")

    elif "gyn" in spec or "obgyn" in spec or "women" in spec:
        questions.append("Am I up to date on cervical cancer screening?")
        questions.append("Should I have a bone density scan?")
        if any("menopause" in c or "perimen" in c for c in conditions):
            questions.append("Is HRT appropriate for me? What are the risks given my history?")

    elif "urol" in spec or "prostate" in spec:
        questions.append("What is my current PSA trend? Should I be concerned?")
        questions.append("Are there lifestyle changes that would help my prostate health?")

    elif "gastro" in spec:
        questions.append("Am I due for a colonoscopy?")
        if any("ibs" in c or "crohn" in c or "colitis" in c for c in conditions):
            questions.append("Is my current treatment still the best option for me?")

    elif "derm" in spec:
        questions.append("Are there any moles or spots I should watch more closely?")

    # Medication review prompt
    if len(meds) >= 3:
        questions.append(f"I'm on {len(meds)} medications — can we review whether all are still needed?")

    return questions[:6]  # Cap at 6 questions


def _outstanding_concerns(profile: dict[str, Any]) -> list[str]:
    concerns: list[str] = []

    # Symptoms from recent check-ins
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    recent = [c for c in profile.get("daily_checkins", []) if c.get("date", "") >= cutoff]
    if recent:
        avg_pain = sum(c.get("pain", 0) for c in recent) / len(recent)
        avg_mood = sum(c.get("mood", 5) for c in recent) / len(recent)
        if avg_pain >= 5:
            concerns.append(f"Ongoing pain (avg {avg_pain:.1f}/10 over 14 days)")
        if avg_mood <= 4:
            concerns.append(f"Low mood (avg {avg_mood:.1f}/10 over 14 days)")

    # Overdue preventive care
    today_str = date.today().isoformat()
    for item in profile.get("preventive_care", []):
        if item.get("next_due", "9999") <= today_str and item.get("overdue"):
            concerns.append(f"Overdue: {item.get('name', 'preventive screen')}")

    # Notes/concerns logged by user
    for note in profile.get("notes", [])[-3:]:
        if isinstance(note, dict):
            text = note.get("text", "")
        else:
            text = str(note)
        if text:
            concerns.append(text)

    return concerns[:5]


# ---------------------------------------------------------------------------
# Appointment CRUD helpers
# ---------------------------------------------------------------------------

def add_appointment(profile: dict[str, Any], date_str: str, specialty: str,
                    reason: str = "", provider: str = "", location: str = "") -> dict[str, Any]:
    """Add an appointment to the profile. Returns the new appointment dict."""
    appt = {
        "date": date_str,
        "specialty": specialty,
        "reason": reason,
        "provider": provider,
        "location": location,
        "status": "upcoming",
    }
    profile.setdefault("appointments", []).append(appt)
    return appt


def list_appointments(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all appointments sorted by date."""
    return sorted(profile.get("appointments", []), key=lambda a: a.get("date", ""))
