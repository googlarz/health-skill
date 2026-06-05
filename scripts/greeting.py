#!/usr/bin/env python3
"""Conversational greeting: reads the workspace and opens with the one most
relevant thing to ask about.  Output is plain prose, no markdown — designed
to be spoken by Claude at the start of a health conversation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import load_profile, load_vital_entries
    from .nudges import compute_nudges
    from .interactions import check_interactions
    from .appointments import get_upcoming_appointments
except ImportError:
    from care_workspace import load_profile, load_vital_entries  # type: ignore
    from nudges import compute_nudges  # type: ignore
    from interactions import check_interactions  # type: ignore
    from appointments import get_upcoming_appointments  # type: ignore


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_ago(d: date) -> int:
    return (date.today() - d).days


def _first_name(name: str) -> str:
    return (name or "").strip().split()[0] if name and name.strip() else ""


def build_greeting(root: Path, person_id: str) -> str:
    """Return a 2-3 sentence conversational opener with a single focused question."""
    profile = load_profile(root, person_id)
    name = _first_name(profile.get("name", ""))
    hi = f"Hey {name}!" if name else "Hey!"
    today = date.today()

    # ── 1. Major drug/supplement interactions ────────────────────────────────
    try:
        alerts = check_interactions(profile)
        major = [a for a in alerts if a.get("severity") == "major"]
        if major:
            item = major[0]
            drugs = item.get("drugs") or []
            if len(drugs) >= 2:
                drug_a, drug_b = drugs[0], drugs[1]
            else:
                drug_a = item.get("drug_a") or item.get("supplement") or "one of your supplements"
                drug_b = item.get("drug_b") or item.get("medication") or "a medication"
            return (
                f"{hi} Before anything else — I flagged a potential major interaction "
                f"between {drug_a} and {drug_b}. "
                f"Have you had a chance to mention this to your doctor or pharmacist?"
            )
    except Exception:
        pass

    # ── 2. High pain for a week ──────────────────────────────────────────────
    checkins = sorted(
        profile.get("daily_checkins", []),
        key=lambda c: str(c.get("date", "")),
    )
    recent_7 = [
        c for c in checkins
        if _parse_date(c.get("date", "")) and _days_ago(_parse_date(c.get("date", ""))) <= 7  # type: ignore[arg-type]
    ]
    pain_vals = [float(c["pain"]) for c in recent_7 if c.get("pain") is not None]
    if len(pain_vals) >= 4 and sum(pain_vals) / len(pain_vals) >= 6.0:
        avg = sum(pain_vals) / len(pain_vals)
        return (
            f"{hi} I noticed your pain has been averaging around {avg:.0f}/10 over the last week. "
            f"How are you feeling today — any better, or still about the same?"
        )

    # ── 3. Burnout signal: sustained low mood + energy ───────────────────────
    recent_14 = [
        c for c in checkins
        if _parse_date(c.get("date", "")) and _days_ago(_parse_date(c.get("date", ""))) <= 14  # type: ignore[arg-type]
    ]
    energy_vals = [float(c["energy"]) for c in recent_14 if c.get("energy") is not None]
    mood_vals = [float(c["mood"]) for c in recent_14 if c.get("mood") is not None]
    if len(energy_vals) >= 5 and len(mood_vals) >= 5:
        avg_e = sum(energy_vals) / len(energy_vals)
        avg_m = sum(mood_vals) / len(mood_vals)
        if avg_e <= 4.0 and avg_m <= 5.0:
            return (
                f"{hi} Your mood and energy have both been on the lower side lately — "
                f"averaging {avg_m:.0f}/10 mood and {avg_e:.0f}/10 energy over the past two weeks. "
                f"What's been going on? Has anything changed recently?"
            )

    # ── 4. Overdue follow-up (> 7 days) ─────────────────────────────────────
    for f in profile.get("follow_up", []):
        if f.get("status") == "completed":
            continue
        due = _parse_date(f.get("due_date", ""))
        if due and _days_ago(due) >= 7:
            task = f.get("task", "a follow-up")
            return (
                f"{hi} You had a follow-up on your list that's been overdue for "
                f"{_days_ago(due)} days: \"{task}\". "
                f"Has that been sorted, or do you need help with it?"
            )

    # ── 5. Upcoming appointment (within 5 days) ──────────────────────────────
    try:
        upcoming = get_upcoming_appointments(profile, days_ahead=5)
        if upcoming:
            appt = upcoming[0]
            appt_date = _parse_date(appt.get("date", ""))
            days_until = (appt_date - today).days if appt_date else None
            provider = appt.get("provider") or appt.get("clinician") or "your provider"
            when = (
                "tomorrow" if days_until == 1
                else "in 2 days" if days_until == 2
                else f"in {days_until} days" if days_until and days_until > 0
                else "soon"
            )
            return (
                f"{hi} You have an appointment with {provider} {when}. "
                f"Want me to put together a pre-visit summary so you're prepared?"
            )
    except Exception:
        pass

    # ── 6. Stale check-in (> 4 days) ─────────────────────────────────────────
    if checkins:
        last_date = _parse_date(checkins[-1].get("date", ""))
        if last_date:
            gap = _days_ago(last_date)
            if gap >= 5:
                last_sleep = checkins[-1].get("sleep_hours")
                sleep_note = (
                    f" Last time you logged you were sleeping around {last_sleep}h —"
                    f" any different lately?"
                    if last_sleep is not None
                    else " How have you been feeling?"
                )
                return (
                    f"{hi} It's been {gap} days since your last check-in.{sleep_note}"
                )

    # ── 7. Active intervention check-in ──────────────────────────────────────
    active_ivs = [
        iv for iv in profile.get("interventions", [])
        if iv.get("status") == "active"
    ]
    if active_ivs:
        iv = active_ivs[0]
        iv_name = iv.get("name", "your intervention")
        start = _parse_date(iv.get("start_date", ""))
        days_in = _days_ago(start) if start else None
        days_str = f" — you're {days_in} days in" if days_in and days_in > 0 else ""
        metric = iv.get("outcome_metric", "")
        metric_q = f" Have you noticed any change in your {metric}?" if metric else " How's it feeling so far?"
        return (
            f"{hi} How's {iv_name} going{days_str}?{metric_q}"
        )

    # ── 8. Recent workout / run ───────────────────────────────────────────────
    recent_runs = [
        w for w in profile.get("workouts", [])
        if w.get("type") == "run"
        and _parse_date(w.get("date", ""))
        and _days_ago(_parse_date(w.get("date", ""))) <= 3  # type: ignore[arg-type]
    ]
    if recent_runs:
        run = sorted(recent_runs, key=lambda w: str(w.get("date", "")))[-1]
        dist = run.get("distance_km")
        dist_str = f"{dist:.1f}km " if dist else ""
        run_date = _parse_date(run.get("date", ""))
        when = "yesterday" if run_date and _days_ago(run_date) == 1 else "recently"
        return (
            f"{hi} Nice work on that {dist_str}run {when}! "
            f"How are you recovering — any soreness or tightness?"
        )

    # ── 9. Recent labs (last 30 days) ────────────────────────────────────────
    recent_labs = [
        t for t in profile.get("recent_tests", [])
        if _parse_date(t.get("date", "")) and _days_ago(_parse_date(t.get("date", ""))) <= 30  # type: ignore[arg-type]
    ]
    if recent_labs:
        lab_names = list({t.get("name", "") for t in recent_labs if t.get("name")})
        lab_str = ", ".join(lab_names[:3])
        return (
            f"{hi} I see you had some recent labs — {lab_str}. "
            f"Would you like me to walk you through what the results mean for you?"
        )

    # ── 10. Sleep deficit nudge ───────────────────────────────────────────────
    sleep_vals_7 = [float(c["sleep_hours"]) for c in recent_7 if c.get("sleep_hours") is not None]
    if len(sleep_vals_7) >= 3 and sum(sleep_vals_7) / len(sleep_vals_7) < 6.5:
        avg_sleep = sum(sleep_vals_7) / len(sleep_vals_7)
        return (
            f"{hi} You've been averaging about {avg_sleep:.1f} hours of sleep this week. "
            f"How are you feeling — is the tiredness catching up with you, or managing okay?"
        )

    # ── 11. Default: fresh opener ─────────────────────────────────────────────
    nudges = compute_nudges(root, person_id)
    high = [n for n in nudges if n.get("priority") == "high"]
    if high:
        return (
            f"{hi} There are {len(high)} things that could use your attention right now. "
            f"Want to start with the most pressing one?"
        )

    if checkins:
        last_date = _parse_date(checkins[-1].get("date", ""))
        gap = _days_ago(last_date) if last_date else None
        if gap is not None and gap <= 1:
            mood = checkins[-1].get("mood")
            mood_str = f" You logged mood {mood}/10 — " if mood else " "
            return (
                f"{hi}{mood_str}how are things going today? Anything you'd like to focus on?"
            )

    return (
        f"{hi} Good to see you. What would you like to focus on today — "
        f"your check-ins, training, labs, or something else?"
    )
