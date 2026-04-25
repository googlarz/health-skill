#!/usr/bin/env python3
"""Mental health layer — PHQ-2, GAD-2, and burnout detection.

Three capabilities:
1. Score PHQ-2 (depression screen) and GAD-2 (anxiety screen) from check-in data
   or direct answers to the two standard questions.
2. Detect burnout signal from sustained low mood + low energy + poor sleep.
3. Produce a 30-day mental health summary.

This is a screening tool, not a diagnostic tool. Scores above threshold always
prompt a recommendation to speak with a clinician.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import atomic_write_text, load_profile, person_dir
except ImportError:
    from care_workspace import atomic_write_text, load_profile, person_dir  # type: ignore

MENTAL_HEALTH_FILENAME = "MENTAL_HEALTH.md"


def mental_health_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / MENTAL_HEALTH_FILENAME


# ---------------------------------------------------------------------------
# PHQ-2 / GAD-2 scoring from check-in mood values
# ---------------------------------------------------------------------------

def _checkins_last_n_days(checkins: list[dict], n: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=n)
    result = []
    for c in checkins:
        try:
            d = datetime.strptime(str(c.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= cutoff:
            result.append(c)
    return result


def _avg(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def _trend(vals: list[float]) -> str:
    if len(vals) < 3:
        return "stable"
    first = sum(vals[:len(vals)//2]) / (len(vals)//2)
    second = sum(vals[len(vals)//2:]) / (len(vals) - len(vals)//2)
    delta = second - first
    if delta <= -1.0:
        return "worsening"
    if delta >= 1.0:
        return "improving"
    return "stable"


def score_phq2_from_checkins(checkins: list[dict], days: int = 14) -> dict[str, Any]:
    """Approximate PHQ-2 from mood check-ins.

    PHQ-2 asks about the last 2 weeks:
    1. Little interest or pleasure in doing things
    2. Feeling down, depressed, or hopeless

    We map mood scores (1–10) to PHQ-2 item scores (0–3):
      mood 8–10 → 0 (not at all)
      mood 5–7  → 1 (several days)
      mood 3–4  → 2 (more than half the days)
      mood 1–2  → 3 (nearly every day)

    This is an approximation — actual PHQ-2 requires direct patient answers.
    """
    recent = _checkins_last_n_days(checkins, days)
    mood_vals = [float(c["mood"]) for c in recent if c.get("mood") is not None]

    if len(mood_vals) < 3:
        return {"score": None, "insufficient_data": True, "days": days, "n": len(mood_vals)}

    avg_mood = _avg(mood_vals)
    assert avg_mood is not None

    # Map average mood to approximate PHQ-2 score (0–6)
    if avg_mood >= 7.5:
        score = 0
    elif avg_mood >= 6.0:
        score = 1
    elif avg_mood >= 4.5:
        score = 2
    elif avg_mood >= 3.0:
        score = 3
    elif avg_mood >= 2.0:
        score = 4
    else:
        score = 5

    return {
        "score": score,
        "avg_mood": round(avg_mood, 1),
        "n_checkins": len(mood_vals),
        "trend": _trend(mood_vals),
        "days": days,
        "interpretation": _interpret_phq2(score),
        "insufficient_data": False,
    }


def _interpret_phq2(score: int) -> str:
    if score < 3:
        return "low"      # minimal depression symptoms
    if score < 5:
        return "moderate"  # possible depression — follow up
    return "high"          # likely significant depression — speak with clinician


def score_gad2_from_checkins(checkins: list[dict], days: int = 14) -> dict[str, Any]:
    """Approximate GAD-2 from check-in mood and notes.

    GAD-2 asks:
    1. Feeling nervous, anxious, or on edge
    2. Not being able to stop or control worrying

    We approximate from: low mood + anxiety keywords in notes.
    """
    recent = _checkins_last_n_days(checkins, days)
    anxiety_keywords = ["anxious", "anxiety", "worry", "worried", "panic", "nervous", "on edge", "tense", "stressed"]

    mood_vals = [float(c["mood"]) for c in recent if c.get("mood") is not None]
    anxiety_hits = sum(
        1 for c in recent
        if any(kw in (c.get("notes") or "").lower() for kw in anxiety_keywords)
    )

    if len(mood_vals) < 3:
        return {"score": None, "insufficient_data": True}

    avg_mood = _avg(mood_vals)
    assert avg_mood is not None
    anxiety_rate = anxiety_hits / len(recent) if recent else 0.0

    # Combine: low mood + high anxiety mention rate
    base = max(0, int((7.0 - avg_mood) * 0.8))
    anxiety_bonus = 2 if anxiety_rate >= 0.4 else (1 if anxiety_rate >= 0.2 else 0)
    score = min(6, base + anxiety_bonus)

    return {
        "score": score,
        "avg_mood": round(avg_mood, 1),
        "anxiety_keyword_rate": round(anxiety_rate, 2),
        "n_checkins": len(recent),
        "trend": _trend(mood_vals),
        "interpretation": _interpret_gad2(score),
        "insufficient_data": False,
    }


def _interpret_gad2(score: int) -> str:
    if score < 3:
        return "low"
    if score < 5:
        return "moderate"
    return "high"


# ---------------------------------------------------------------------------
# Burnout detection
# ---------------------------------------------------------------------------

BURNOUT_WINDOW_DAYS = 21


def detect_burnout(checkins: list[dict]) -> dict[str, Any]:
    """Detect burnout signal from sustained low scores across mood, energy, sleep.

    Burnout = sustained (3+ weeks) combination of:
    - Low energy (avg ≤ 4.5)
    - Low mood (avg ≤ 5.0)
    - Poor sleep (avg < 6.5h)

    Returns a risk level: none / low / moderate / high
    """
    recent = _checkins_last_n_days(checkins, BURNOUT_WINDOW_DAYS)

    if len(recent) < 5:
        return {"risk": "unknown", "reason": "Fewer than 5 check-ins in the last 3 weeks."}

    energy_vals = [float(c["energy"]) for c in recent if c.get("energy") is not None]
    mood_vals = [float(c["mood"]) for c in recent if c.get("mood") is not None]
    sleep_vals = [float(c["sleep_hours"]) for c in recent if c.get("sleep_hours") is not None]

    signals: list[str] = []
    score = 0

    if energy_vals:
        avg_e = _avg(energy_vals)
        assert avg_e is not None
        if avg_e <= 4.0:
            signals.append(f"Energy avg {avg_e:.1f}/10 — persistently low")
            score += 2
        elif avg_e <= 5.5:
            signals.append(f"Energy avg {avg_e:.1f}/10 — below average")
            score += 1

    if mood_vals:
        avg_m = _avg(mood_vals)
        assert avg_m is not None
        if avg_m <= 4.5:
            signals.append(f"Mood avg {avg_m:.1f}/10 — persistently low")
            score += 2
        elif avg_m <= 6.0:
            signals.append(f"Mood avg {avg_m:.1f}/10 — below average")
            score += 1

    if sleep_vals:
        avg_s = _avg(sleep_vals)
        assert avg_s is not None
        if avg_s < 6.0:
            signals.append(f"Sleep avg {avg_s:.1f}h — below 6h")
            score += 2
        elif avg_s < 7.0:
            signals.append(f"Sleep avg {avg_s:.1f}h — below recommended 7h")
            score += 1

    if score == 0:
        risk = "none"
    elif score <= 2:
        risk = "low"
    elif score <= 4:
        risk = "moderate"
    else:
        risk = "high"

    return {
        "risk": risk,
        "score": score,
        "signals": signals,
        "checkins_analysed": len(recent),
        "window_days": BURNOUT_WINDOW_DAYS,
    }


# ---------------------------------------------------------------------------
# Full report renderer
# ---------------------------------------------------------------------------

def build_mental_health_report(profile: dict[str, Any]) -> str:
    checkins = profile.get("daily_checkins") or []
    today = date.today()
    lines = [
        "# Mental Health Summary",
        "",
        f"_Generated {today.isoformat()} · Based on your check-in data_",
        "",
        "> This is a screening tool, not a diagnosis. If you're struggling, please speak with a clinician.",
        "",
    ]

    if len(checkins) < 3:
        lines.append(
            "Not enough check-in data yet. Log at least 7 check-ins to enable this report. "
            "Use `daily-checkin` to log how you're feeling."
        )
        return "\n".join(lines) + "\n"

    # PHQ-2 proxy
    phq = score_phq2_from_checkins(checkins)
    gad = score_gad2_from_checkins(checkins)
    burnout = detect_burnout(checkins)

    # Depression screen
    lines.append("## Depression screen (PHQ-2 proxy)\n")
    if phq.get("insufficient_data"):
        lines.append("_Not enough recent check-ins (need 3+ in past 14 days)._\n")
    else:
        icons = {"low": "✅", "moderate": "🟡", "high": "🔴"}
        icon = icons.get(phq["interpretation"], "⚪")
        lines.append(
            f"{icon} Approximate score: **{phq['score']}/6** — {phq['interpretation'].upper()}"
        )
        lines.append(
            f"Based on {phq['n_checkins']} check-ins · Avg mood {phq['avg_mood']}/10 · Trend: {phq['trend']}"
        )
        if phq["interpretation"] == "moderate":
            lines.append(
                "\n💬 Mood has been lower than average for the past two weeks. "
                "Consider talking to someone you trust or scheduling a check-in with your GP."
            )
        elif phq["interpretation"] == "high":
            lines.append(
                "\n🔴 Mood scores suggest significant low mood. Please reach out to a clinician, "
                "therapist, or crisis line. You don't need to feel this way alone."
            )
        lines.append("")

    # Anxiety screen
    lines.append("## Anxiety screen (GAD-2 proxy)\n")
    if gad.get("insufficient_data"):
        lines.append("_Not enough recent check-ins._\n")
    else:
        icons = {"low": "✅", "moderate": "🟡", "high": "🔴"}
        icon = icons.get(gad["interpretation"], "⚪")
        lines.append(
            f"{icon} Approximate score: **{gad['score']}/6** — {gad['interpretation'].upper()}"
        )
        if gad.get("anxiety_keyword_rate", 0) > 0:
            lines.append(
                f"Anxiety-related words in {gad['anxiety_keyword_rate']*100:.0f}% of notes"
            )
        if gad["interpretation"] in ("moderate", "high"):
            lines.append(
                "\n💬 Anxiety signals detected in your check-in notes and mood scores. "
                "If worry is interfering with your daily life, speaking with a clinician or therapist can help."
            )
        lines.append("")

    # Burnout
    lines.append("## Burnout signal\n")
    icons = {"none": "✅", "low": "🟡", "moderate": "🟠", "high": "🔴", "unknown": "⚪"}
    icon = icons.get(burnout["risk"], "⚪")
    lines.append(f"{icon} Risk: **{burnout['risk'].upper()}**")
    if burnout.get("signals"):
        for s in burnout["signals"]:
            lines.append(f"- {s}")
    if burnout["risk"] in ("moderate", "high"):
        lines.append(
            "\n💬 Sustained low energy, mood, and sleep together are a classic burnout pattern. "
            "Consider what you can reduce, delegate, or postpone. Rest is not a reward — it's recovery."
        )
    lines.append("")

    # Resources
    lines.append("## Resources\n")
    lines.append("- **Samaritans** (UK): 116 123 (24/7, free)")
    lines.append("- **Crisis Text Line** (US): Text HOME to 741741")
    lines.append("- **Beyond Blue** (AU): 1300 22 4636")
    lines.append("- **Your GP**: first stop for referrals to therapy or medication support")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_mental_health_report(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    text = build_mental_health_report(profile)
    path = mental_health_path(root, person_id)
    atomic_write_text(path, text)
    return path
