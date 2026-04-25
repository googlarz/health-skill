#!/usr/bin/env python3
"""Medication side-effect timeline.

When a new medication is added to the profile, this module watches subsequent
daily check-ins for known side effects of that medication and flags correlations.

Example output:
  metformin started 2024-03-01
  → GI discomfort scores: avg 1.2 before → avg 3.8 in first 3 weeks
  → Possible metformin GI side effect. Usually resolves. Consider taking with food.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Side-effect database
# Each entry: medication keywords, checkin fields to watch, threshold,
# window_days (how long after starting to monitor), message
# ---------------------------------------------------------------------------

SIDE_EFFECT_PROFILES: list[dict[str, Any]] = [
    # Metformin — GI
    {
        "medication": ["metformin"],
        "watch": {"pain": "GI discomfort or pain", "notes_keywords": ["nausea", "stomach", "diarrhea", "diarrhoea", "vomit", "gi", "gut", "bowel"]},
        "window_days": 28,
        "effect_name": "GI side effects",
        "message": "GI side effects are common with metformin, especially in the first weeks. Usually improves. Take with food or ask about extended-release formulation.",
        "severity": "common",
    },
    # SSRIs — sleep, mood, energy
    {
        "medication": ["sertraline", "fluoxetine", "escitalopram", "citalopram", "paroxetine", "ssri"],
        "watch": {"sleep_hours": "sleep disruption", "mood": "mood change", "notes_keywords": ["nausea", "headache", "anxious", "anxiety", "insomnia", "tired", "fatigue"]},
        "window_days": 42,
        "effect_name": "SSRI initiation effects",
        "message": "SSRIs often cause transient nausea, sleep changes, and initial anxiety in the first 2–4 weeks. These typically resolve. If worsening after 6 weeks, discuss with prescriber.",
        "severity": "common",
    },
    # Levothyroxine — over-replacement
    {
        "medication": ["levothyroxine", "synthroid"],
        "watch": {"mood": "anxiety or mood change", "sleep_hours": "sleep disruption", "notes_keywords": ["heart racing", "palpitation", "anxious", "shaky", "tremor", "sweat"]},
        "window_days": 56,
        "effect_name": "Levothyroxine over-replacement signs",
        "message": "Palpitations, anxiety, insomnia, or heat intolerance after a dose change may suggest over-replacement. Check TSH.",
        "severity": "monitor",
    },
    # Statins — muscle pain
    {
        "medication": ["statin", "simvastatin", "atorvastatin", "rosuvastatin", "pravastatin", "lovastatin"],
        "watch": {"pain": "muscle pain", "notes_keywords": ["muscle", "myalgia", "cramp", "ache", "weakness", "tired", "fatigue"]},
        "window_days": 90,
        "effect_name": "Statin myalgia",
        "message": "Muscle aches starting after a statin can be drug-related. Note whether pain is symmetrical and proximal (thighs, shoulders). Discuss with prescriber — CK level may be worth checking.",
        "severity": "monitor",
    },
    # ACE inhibitors — cough
    {
        "medication": ["lisinopril", "ramipril", "enalapril", "perindopril", "captopril", "ace inhibitor"],
        "watch": {"notes_keywords": ["cough", "dry cough", "tickle", "throat"]},
        "window_days": 90,
        "effect_name": "ACE inhibitor cough",
        "message": "A persistent dry cough affects ~10–15% of ACE inhibitor users. If bothersome, discuss switching to an ARB (losartan, valsartan) with your prescriber.",
        "severity": "common",
    },
    # Beta-blockers — fatigue, cold extremities
    {
        "medication": ["metoprolol", "atenolol", "bisoprolol", "propranolol", "carvedilol", "beta-blocker"],
        "watch": {"energy": "fatigue", "notes_keywords": ["tired", "fatigue", "cold", "hands", "feet", "slow"]},
        "window_days": 56,
        "effect_name": "Beta-blocker fatigue",
        "message": "Fatigue and cold extremities are common beta-blocker effects. Usually improves over 4–6 weeks. If significant, discuss dose adjustment.",
        "severity": "common",
    },
    # Corticosteroids — mood, sleep, blood sugar
    {
        "medication": ["prednisone", "prednisolone", "dexamethasone", "hydrocortisone", "methylprednisolone"],
        "watch": {"mood": "mood change", "sleep_hours": "sleep disruption", "notes_keywords": ["anxious", "irritable", "insomnia", "hungry", "thirst", "sugar"]},
        "window_days": 30,
        "effect_name": "Corticosteroid effects",
        "message": "Mood changes, insomnia, increased appetite, and elevated blood sugar are common on corticosteroids. Monitor blood glucose if diabetic.",
        "severity": "common",
    },
]


def _med_started_recently(medication: dict[str, Any]) -> date | None:
    """Return the start date if available, else None."""
    raw = medication.get("start_date") or medication.get("started") or ""
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _checkins_in_window(
    checkins: list[dict[str, Any]], after: date, days: int
) -> list[dict[str, Any]]:
    end = after + timedelta(days=days)
    result = []
    for c in checkins:
        try:
            d = datetime.strptime(str(c.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if after <= d <= end:
            result.append(c)
    return result


def _checkins_before(
    checkins: list[dict[str, Any]], before: date, window_days: int = 30
) -> list[dict[str, Any]]:
    start = before - timedelta(days=window_days)
    result = []
    for c in checkins:
        try:
            d = datetime.strptime(str(c.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d < before:
            result.append(c)
    return result


def _avg_field(checkins: list[dict[str, Any]], field: str) -> float | None:
    vals = [float(c[field]) for c in checkins if c.get(field) is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _keyword_hit_rate(checkins: list[dict[str, Any]], keywords: list[str]) -> float:
    if not checkins:
        return 0.0
    hits = 0
    for c in checkins:
        notes = (c.get("notes") or "").lower()
        if any(kw in notes for kw in keywords):
            hits += 1
    return hits / len(checkins)


def _analyse_medication(
    med: dict[str, Any],
    profile_rule: dict[str, Any],
    checkins: list[dict[str, Any]],
    today: date,
) -> dict[str, Any] | None:
    """Return a finding dict if a side-effect signal is detected, else None."""
    start = _med_started_recently(med)
    if not start:
        return None

    days_since = (today - start).days
    if days_since < 3:  # too new
        return None

    monitor_window = min(profile_rule["window_days"], days_since)
    after_checkins = _checkins_in_window(checkins, start, monitor_window)
    before_checkins = _checkins_before(checkins, start, 30)

    if len(after_checkins) < 2:  # not enough data
        return None

    watch = profile_rule["watch"]
    signals: list[str] = []

    # Numeric fields
    for field, label in [(k, v) for k, v in watch.items() if k != "notes_keywords"]:
        before_avg = _avg_field(before_checkins, field)
        after_avg = _avg_field(after_checkins, field)
        if before_avg is None or after_avg is None:
            continue
        delta = after_avg - before_avg
        # pain: increase is bad; mood/energy/sleep: decrease is bad
        if field == "pain" and delta >= 2.0:
            signals.append(f"{label}: avg {before_avg:.1f} → {after_avg:.1f} (+{delta:.1f}) after starting {med.get('name')}")
        elif field in ("mood", "energy") and delta <= -2.0:
            signals.append(f"{label}: avg {before_avg:.1f} → {after_avg:.1f} ({delta:.1f}) after starting {med.get('name')}")
        elif field == "sleep_hours" and delta <= -0.75:
            signals.append(f"{label}: avg {before_avg:.1f}h → {after_avg:.1f}h ({delta:+.1f}h) after starting {med.get('name')}")

    # Keyword mentions in notes
    keywords = watch.get("notes_keywords", [])
    if keywords:
        before_rate = _keyword_hit_rate(before_checkins, keywords)
        after_rate = _keyword_hit_rate(after_checkins, keywords)
        if after_rate >= 0.25 and after_rate >= before_rate + 0.15:
            signals.append(
                f"Symptom mentions in notes: {after_rate * 100:.0f}% of check-ins after starting "
                f"{med.get('name')} (vs {before_rate * 100:.0f}% before)"
            )

    if not signals:
        return None

    return {
        "medication": med.get("name", "?"),
        "started": start.isoformat(),
        "effect_name": profile_rule["effect_name"],
        "severity": profile_rule["severity"],
        "message": profile_rule["message"],
        "signals": signals,
        "days_monitored": monitor_window,
        "checkins_analysed": len(after_checkins),
    }


def analyse_side_effects(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of side-effect findings for all medications in the profile."""
    medications = profile.get("medications") or []
    checkins = profile.get("daily_checkins") or []
    today = date.today()
    findings: list[dict[str, Any]] = []

    for med in medications:
        med_name = (med.get("name") or "").lower()
        for rule in SIDE_EFFECT_PROFILES:
            if not any(kw in med_name or med_name.startswith(kw) for kw in rule["medication"]):
                continue
            finding = _analyse_medication(med, rule, checkins, today)
            if finding:
                findings.append(finding)

    return findings


def render_side_effects_text(profile: dict[str, Any]) -> str:
    findings = analyse_side_effects(profile)
    if not findings:
        return (
            "# Medication Side-Effect Timeline\n\n"
            "No side-effect signals detected in your check-in data.\n\n"
            "_This analysis compares your mood, sleep, energy, and pain scores "
            "before and after each medication start date. More check-in data improves accuracy._\n"
        )

    lines = ["# Medication Side-Effect Timeline\n"]
    lines.append(
        f"Found **{len(findings)}** possible side-effect signal(s) "
        "based on your check-in data:\n"
    )

    icons = {"common": "🟡", "monitor": "🟠", "serious": "🔴"}
    for f in findings:
        icon = icons.get(f["severity"], "⚪")
        lines.append(f"## {icon} {f['medication']} — {f['effect_name']}\n")
        lines.append(f"Started: {f['started']} · Analysed {f['checkins_analysed']} check-ins over {f['days_monitored']} days\n")
        lines.append("**Signal(s) detected:**")
        for s in f["signals"]:
            lines.append(f"- {s}")
        lines.append(f"\n**What this might mean:** {f['message']}\n")

    lines.append(
        "_These are signals worth discussing with your prescriber — not a diagnosis. "
        "Correlation in check-in data is not the same as causation._\n"
    )
    return "\n".join(lines)
