#!/usr/bin/env python3
"""Training log and workout-plan generator for Health Skill v1.7."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import upsert_record, load_profile
except ImportError:
    from care_workspace import upsert_record, load_profile


SAFETY_NOTE = (
    "This is a general training plan. If you have injuries, a physical therapist "
    "or certified trainer should review it. Stop any exercise that causes sharp pain."
)


# Exercise bank: ~40 exercises with target areas, equipment, and contraindications.
EXERCISE_BANK: dict[str, dict[str, Any]] = {
    # Posture / upper back
    "Face Pulls":         {"targets": ["upper back", "posture", "rear delts"], "equipment": ["resistance bands", "cable"], "contra": []},
    "Band Pull-Aparts":   {"targets": ["upper back", "posture"], "equipment": ["resistance bands"], "contra": []},
    "Wall Angels":        {"targets": ["posture", "mobility"], "equipment": [], "contra": []},
    "Chin Tucks":         {"targets": ["neck", "posture"], "equipment": [], "contra": []},
    "Prone Y-T-W":        {"targets": ["upper back", "posture"], "equipment": [], "contra": []},
    "Scapular Retraction":{"targets": ["upper back", "posture"], "equipment": [], "contra": []},
    "Thoracic Extension": {"targets": ["mobility", "posture"], "equipment": ["foam roller"], "contra": []},
    # Strength (compound)
    "Goblet Squat":       {"targets": ["legs", "strength"], "equipment": ["dumbbells", "kettlebell"], "contra": []},
    "Romanian Deadlift":  {"targets": ["posterior chain", "strength"], "equipment": ["dumbbells", "barbell"], "contra": ["lower back"]},
    "Bench Press":        {"targets": ["chest", "strength"], "equipment": ["barbell", "dumbbells"], "contra": ["shoulder"]},
    "Overhead Press":     {"targets": ["shoulder", "strength"], "equipment": ["dumbbells", "barbell"], "contra": ["shoulder"]},
    "Bent-Over Row":      {"targets": ["back", "strength"], "equipment": ["dumbbells", "barbell"], "contra": ["lower back"]},
    "Seated Row":         {"targets": ["back", "posture"], "equipment": ["resistance bands", "cable"], "contra": []},
    "Lat Pulldown":       {"targets": ["back", "strength"], "equipment": ["cable", "resistance bands"], "contra": []},
    "Pull-Up":            {"targets": ["back", "strength"], "equipment": ["pull-up bar"], "contra": []},
    "Push-Up":            {"targets": ["chest", "strength"], "equipment": [], "contra": ["shoulder"]},
    "Plank":              {"targets": ["core", "strength"], "equipment": [], "contra": []},
    "Dead Bug":           {"targets": ["core", "rehab"], "equipment": [], "contra": []},
    "Bird Dog":           {"targets": ["core", "lower back", "rehab"], "equipment": [], "contra": []},
    "Glute Bridge":       {"targets": ["glutes", "lower back", "rehab"], "equipment": [], "contra": []},
    "Hip Thrust":         {"targets": ["glutes", "strength"], "equipment": ["dumbbells", "barbell"], "contra": []},
    "Lunge":              {"targets": ["legs", "strength"], "equipment": [], "contra": ["knee"]},
    "Step-Up":            {"targets": ["legs", "strength"], "equipment": ["dumbbells"], "contra": ["knee"]},
    # Endurance / cardio
    "Brisk Walk":         {"targets": ["endurance", "weight loss"], "equipment": [], "contra": []},
    "Easy Run":           {"targets": ["endurance"], "equipment": [], "contra": ["knee"]},
    "Interval Run":       {"targets": ["endurance", "weight loss"], "equipment": [], "contra": ["knee"]},
    "Cycling":            {"targets": ["endurance", "weight loss"], "equipment": ["bike"], "contra": []},
    "Rowing":             {"targets": ["endurance", "back", "weight loss"], "equipment": ["rower"], "contra": ["lower back"]},
    "Jump Rope":          {"targets": ["endurance", "weight loss"], "equipment": ["rope"], "contra": ["knee"]},
    # Mobility / rehab
    "Cat-Cow":            {"targets": ["mobility", "lower back"], "equipment": [], "contra": []},
    "Hip Flexor Stretch": {"targets": ["mobility", "rehab"], "equipment": [], "contra": []},
    "Hamstring Stretch":  {"targets": ["mobility", "rehab"], "equipment": [], "contra": []},
    "Pigeon Pose":        {"targets": ["mobility", "hips"], "equipment": [], "contra": []},
    "Child's Pose":       {"targets": ["mobility", "lower back"], "equipment": [], "contra": []},
    "Downward Dog":       {"targets": ["mobility"], "equipment": [], "contra": ["shoulder"]},
    "Foam Roll Thoracic": {"targets": ["mobility", "posture"], "equipment": ["foam roller"], "contra": []},
    "McGill Curl-Up":     {"targets": ["core", "rehab", "lower back"], "equipment": [], "contra": []},
    "Side Plank":         {"targets": ["core", "rehab"], "equipment": [], "contra": ["shoulder"]},
    "Farmer Carry":       {"targets": ["core", "strength", "posture"], "equipment": ["dumbbells", "kettlebell"], "contra": []},
    "Dumbbell Row":       {"targets": ["back", "posture"], "equipment": ["dumbbells"], "contra": ["lower back"]},
    "Reverse Fly":        {"targets": ["rear delts", "posture"], "equipment": ["dumbbells", "resistance bands"], "contra": []},
}


GOAL_KEYWORDS = {
    "posture":         ["posture", "upper back", "rear delts", "mobility"],
    "strength":        ["strength", "legs", "back", "chest", "shoulder", "core"],
    "endurance":       ["endurance"],
    "weight loss":     ["weight loss", "endurance"],
    "rehab":           ["rehab", "mobility", "core"],
    "mobility":        ["mobility"],
    "menopause":       ["strength", "legs", "glutes", "posterior chain", "core"],
    "bone density":    ["strength", "legs", "glutes", "posterior chain"],
    "muscle mass":     ["strength", "legs", "back", "chest"],
    "hormonal health": ["strength", "legs", "glutes", "core", "endurance"],
}


def _normalize_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [part.strip().lower() for part in re.split(r"[,;]", value) if part.strip()]
    return []


def parse_workout(text: str) -> dict[str, Any]:
    """Parse a natural-language workout description."""
    t = (text or "").strip()
    low = t.lower()
    result: dict[str, Any] = {
        "type": "",
        "duration_min": None,
        "distance_km": None,
        "exercises": [],
        "notes": "",
        "intensity": "",
    }

    # Type heuristic
    if "run" in low or "running" in low or re.search(r"\b\d+\s*k\b", low):
        result["type"] = "run"
    elif "yoga" in low:
        result["type"] = "yoga"
    elif "pt " in low or "physical therapy" in low or "pt exercises" in low:
        result["type"] = "pt"
    elif "bike" in low or "cycling" in low or "ride" in low:
        result["type"] = "cycling"
    elif "upper body" in low:
        result["type"] = "strength_upper"
    elif "lower body" in low or "leg day" in low:
        result["type"] = "strength_lower"
    elif "swim" in low:
        result["type"] = "swim"
    elif any(w in low for w in ("bench", "squat", "deadlift", "press", "row", "curl")):
        result["type"] = "strength"
    else:
        result["type"] = "workout"

    # Duration
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minutes?|m\b)", low)
    if m:
        result["duration_min"] = float(m.group(1))
    else:
        m = re.search(r"(\d+)\s*:\s*(\d{2})", t)  # 28:30 format
        if m:
            result["duration_min"] = int(m.group(1)) + int(m.group(2)) / 60.0

    # Distance: "5k" or "5 km" or "3 miles"
    m = re.search(r"(\d+(?:\.\d+)?)\s*k(?:m)?\b", low)
    if m:
        result["distance_km"] = float(m.group(1))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*miles?\b", low)
        if m:
            result["distance_km"] = round(float(m.group(1)) * 1.60934, 2)

    # Exercises: "bench 80kg 5x5", "rows 60kg 3x10"
    ex_pattern = re.compile(
        r"([A-Za-z][A-Za-z \-]+?)\s+(\d+(?:\.\d+)?)\s*(kg|lb|lbs)\s+(\d+)\s*[x×]\s*(\d+)",
        re.IGNORECASE,
    )
    for m in ex_pattern.finditer(t):
        name, weight, unit, sets, reps = m.groups()
        w = float(weight)
        if unit.lower().startswith("lb"):
            w = round(w * 0.453592, 2)
        result["exercises"].append({
            "name": name.strip().title(),
            "weight_kg": w,
            "sets": int(sets),
            "reps": int(reps),
        })

    # Intensity
    if "felt great" in low or "easy" in low or "felt good" in low:
        result["intensity"] = "easy"
    elif "hard" in low or "tough" in low or "brutal" in low:
        result["intensity"] = "hard"
    elif "moderate" in low:
        result["intensity"] = "moderate"

    result["notes"] = t
    return result


def log_workout(root: Path, person_id: str, workout: dict[str, Any]) -> dict[str, Any]:
    """Save a workout and detect PRs."""
    today = date.today().isoformat()
    record = dict(workout)
    record.setdefault("date", today)

    # PR detection: compare exercise weights against history
    profile = load_profile(root, person_id)
    prior = profile.get("workouts", []) or []
    prior_max: dict[str, float] = {}
    for w in prior:
        for ex in w.get("exercises", []) or []:
            name = ex.get("name", "")
            weight = ex.get("weight_kg")
            if name and isinstance(weight, (int, float)):
                prior_max[name.lower()] = max(prior_max.get(name.lower(), 0.0), float(weight))

    new_prs: list[dict[str, Any]] = []
    for ex in record.get("exercises", []) or []:
        name = ex.get("name", "")
        weight = ex.get("weight_kg")
        if not name or not isinstance(weight, (int, float)):
            continue
        if float(weight) > prior_max.get(name.lower(), 0.0):
            new_prs.append({
                "exercise": name,
                "category": "weight",
                "value": float(weight),
                "unit": "kg",
                "reps": ex.get("reps"),
                "date": record["date"],
            })

    # Distance/time PRs
    if record.get("type") == "run" and record.get("distance_km") and record.get("duration_min"):
        label = f"{record['distance_km']}k run"
        best = None
        for w in prior:
            if w.get("type") == "run" and w.get("distance_km") == record["distance_km"] and w.get("duration_min"):
                if best is None or w["duration_min"] < best:
                    best = w["duration_min"]
        if best is None or record["duration_min"] < best:
            new_prs.append({
                "exercise": label,
                "category": "time",
                "value": record["duration_min"],
                "unit": "min",
                "date": record["date"],
            })

    upsert_record(
        root, person_id, "workouts", record,
        source_type="user", source_label="workout-log", source_date=record["date"],
    )
    for pr in new_prs:
        upsert_record(
            root, person_id, "personal_records", pr,
            source_type="user", source_label="workout-log", source_date=record["date"],
        )

    return {"workout": record, "new_prs": new_prs}


def _parse_sessions_per_week(available: str) -> tuple[int, int]:
    """Return (sessions, minutes) from strings like '3x30min per week'."""
    low = (available or "").lower()
    sessions = 3
    minutes = 30
    m = re.search(r"(\d+)\s*x\s*(\d+)\s*min", low)
    if m:
        sessions = int(m.group(1))
        minutes = int(m.group(2))
    else:
        m = re.search(r"(\d+)\s*(?:sessions?|times?|days?)\s*(?:per|a)\s*week", low)
        if m:
            sessions = int(m.group(1))
        m = re.search(r"(\d+)\s*min", low)
        if m:
            minutes = int(m.group(1))
    sessions = max(1, min(sessions, 7))
    minutes = max(10, min(minutes, 120))
    return sessions, minutes


def _classify_goal(goal: str) -> list[str]:
    low = (goal or "").lower()
    matched: list[str] = []
    for key in GOAL_KEYWORDS:
        if key in low:
            matched.append(key)
    if "rounded shoulders" in low or "hunched" in low:
        if "posture" not in matched:
            matched.append("posture")
    if "stronger" in low and "strength" not in matched:
        matched.append("strength")
    if not matched:
        matched = ["strength", "mobility"]
    return matched


def _exercise_allowed(ex_name: str, ex_data: dict[str, Any], equipment: list[str], injuries: list[str]) -> bool:
    # Equipment filter: if exercise requires equipment, at least one must be available OR none required
    req = ex_data.get("equipment", []) or []
    if req:
        if not any(e.lower() in [x.lower() for x in equipment] for e in req):
            return False
    # Injury filter: exclude if contra overlaps
    contra = [c.lower() for c in ex_data.get("contra", []) or []]
    for inj in injuries:
        for c in contra:
            if c in inj or inj in c:
                return False
    return True


def generate_workout_plan(
    goal: str,
    available_sessions: str,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a structured training plan."""
    constraints = constraints or {}
    equipment = _normalize_list(constraints.get("equipment"))
    injuries = _normalize_list(constraints.get("injuries"))
    sessions_per_week, minutes = _parse_sessions_per_week(available_sessions)
    categories = _classify_goal(goal)

    # Collect target areas from goal categories
    target_areas: list[str] = []
    for cat in categories:
        for t in GOAL_KEYWORDS.get(cat, []):
            if t not in target_areas:
                target_areas.append(t)

    # Filter exercise bank
    candidates: list[tuple[str, dict[str, Any]]] = []
    for name, data in EXERCISE_BANK.items():
        if not _exercise_allowed(name, data, equipment, injuries):
            continue
        if any(t in data.get("targets", []) for t in target_areas):
            candidates.append((name, data))

    # Build sessions -- rotate exercises across sessions, 4-6 exercises per session
    ex_per_session = max(4, min(6, minutes // 6))
    session_names_by_count = {
        1: ["Session A: Full Body"],
        2: ["Session A: Upper / Posture", "Session B: Lower / Core"],
        3: ["Session A: Upper Back & Posture", "Session B: Lower & Core", "Session C: Mobility & Strength"],
        4: ["Session A: Upper", "Session B: Lower", "Session C: Posture & Core", "Session D: Mobility"],
        5: ["Session A: Upper", "Session B: Lower", "Session C: Posture", "Session D: Core", "Session E: Mobility"],
        6: ["Session A", "Session B", "Session C", "Session D", "Session E", "Session F"],
        7: [f"Session {c}" for c in "ABCDEFG"],
    }
    session_names = session_names_by_count.get(sessions_per_week, [f"Session {i+1}" for i in range(sessions_per_week)])

    sessions: list[dict[str, Any]] = []
    if not candidates:
        # Fallback: unfiltered bodyweight set
        candidates = [
            (n, d) for n, d in EXERCISE_BANK.items()
            if not d.get("equipment") and _exercise_allowed(n, d, equipment, injuries)
        ]

    for i in range(sessions_per_week):
        picks: list[dict[str, Any]] = []
        # Round-robin through candidates offset by session index
        for j in range(ex_per_session):
            idx = (i + j * sessions_per_week) % max(1, len(candidates))
            name, data = candidates[idx]
            # Assign sets/reps by category
            targets = data.get("targets", [])
            if "mobility" in targets or "rehab" in targets:
                sets, reps, notes = 2, 10, "Slow, controlled reps; focus on form."
            elif "endurance" in targets or "weight loss" in targets:
                sets, reps, notes = 1, 0, f"{max(10, minutes // 2)} min continuous."
            elif "posture" in targets:
                sets, reps, notes = 3, 12, "Squeeze shoulder blades; pause 1-2s at end range."
            else:
                sets, reps, notes = 3, 8, "Leave 1-2 reps in reserve; progress weight gradually."
            picks.append({"name": name, "sets": sets, "reps": reps, "notes": notes})
        # Deduplicate within session while preserving order
        seen = set()
        unique_picks: list[dict[str, Any]] = []
        for p in picks:
            if p["name"] not in seen:
                seen.add(p["name"])
                unique_picks.append(p)
        sessions.append({
            "name": session_names[i] if i < len(session_names) else f"Session {i+1}",
            "duration_min": minutes,
            "exercises": unique_picks,
        })

    safety_notes = [SAFETY_NOTE]
    for inj in injuries:
        safety_notes.append(f"Stop if {inj} pain increases; substitute or skip affected exercises.")
    if not injuries:
        safety_notes.append("Warm up 5 minutes before each session.")

    # Duration: 8 weeks default; 6 for mobility/rehab-heavy
    duration_weeks = 6 if categories == ["mobility"] or categories == ["rehab"] else 8

    plan_name_cat = "/".join(c.title() for c in categories[:2]) or "General Training"
    plan = {
        "name": f"{plan_name_cat} - {sessions_per_week}x{minutes}min",
        "goal": goal,
        "duration_weeks": duration_weeks,
        "sessions_per_week": sessions_per_week,
        "sessions": sessions,
        "progression": (
            "Week 1-2 learn form and establish baseline. "
            "Week 3-5 add ~10% weight or 1-2 reps per set when all sets feel solid. "
            f"Week 6-{duration_weeks} add a set or increase intensity; deload if fatigued."
        ),
        "safety_notes": safety_notes,
        "equipment_used": equipment,
        "injuries_considered": injuries,
        "created_at": date.today().isoformat(),
    }
    return plan


def render_training_text(profile: dict[str, Any]) -> str:
    """Render TRAINING.md with recent workouts, PRs, and current plan."""
    workouts = list(profile.get("workouts", []) or [])
    prs = list(profile.get("personal_records", []) or [])
    plans = list(profile.get("workout_plans", []) or [])

    lines = ["# Training", ""]

    if plans:
        current = plans[-1]
        lines.append("## Current plan")
        lines.append(f"- **{current.get('name','?')}** — {current.get('sessions_per_week','?')}x/week, "
                     f"{current.get('duration_weeks','?')} weeks")
        lines.append(f"- Goal: {current.get('goal','-')}")
        if current.get("progression"):
            lines.append(f"- Progression: {current['progression']}")
        lines.append("")

    lines.append("## Recent workouts")
    if workouts:
        workouts_sorted = sorted(workouts, key=lambda w: w.get("date", ""), reverse=True)
        for w in workouts_sorted[:10]:
            d = w.get("date", "?")
            typ = w.get("type", "workout")
            dur = w.get("duration_min")
            dist = w.get("distance_km")
            parts = [d, typ]
            if dur: parts.append(f"{dur}min")
            if dist: parts.append(f"{dist}km")
            ex_count = len(w.get("exercises", []) or [])
            if ex_count:
                parts.append(f"{ex_count} exercises")
            lines.append(f"- {' | '.join(str(p) for p in parts)}")
    else:
        lines.append("_No workouts logged yet._")
    lines.append("")

    lines.append("## Personal records")
    if prs:
        prs_sorted = sorted(prs, key=lambda p: p.get("date", ""), reverse=True)
        for pr in prs_sorted[:10]:
            lines.append(
                f"- **{pr.get('exercise','?')}**: {pr.get('value','?')} {pr.get('unit','')} "
                f"({pr.get('date','?')})"
            )
    else:
        lines.append("_No PRs recorded yet._")
    lines.append("")
    lines.append(f"> {SAFETY_NOTE}")
    lines.append("")
    return "\n".join(lines)


def command_workout_log(args: argparse.Namespace) -> int:
    root = Path(args.root)
    parsed = parse_workout(args.text)
    saved = log_workout(root, args.person_id, parsed)
    print(f"Logged workout: {saved['workout']}")
    if saved["new_prs"]:
        print(f"New PRs: {saved['new_prs']}")
    return 0


def command_workout_plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    constraints = {
        "equipment": _normalize_list(getattr(args, "equipment", "")),
        "injuries": _normalize_list(getattr(args, "injuries", "")),
    }
    plan = generate_workout_plan(args.goal, args.available, constraints)
    upsert_record(
        root, args.person_id, "workout_plans", plan,
        source_type="user", source_label="plan-generator", source_date=plan["created_at"],
    )
    print(f"Generated plan: {plan['name']}")
    print(f"Sessions ({plan['sessions_per_week']}/week):")
    for s in plan["sessions"]:
        print(f"  {s['name']}:")
        for ex in s["exercises"]:
            print(f"    - {ex['name']}: {ex['sets']}x{ex['reps']} — {ex['notes']}")
    print(f"\nProgression: {plan['progression']}")
    for note in plan["safety_notes"]:
        print(f"  ! {note}")
    return 0
