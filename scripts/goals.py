#!/usr/bin/env python3
"""Goal setting and progress tracking.

Goals are stored in HEALTH_PROFILE.json under `goals`. Each goal has:
  id, title, target, metric, unit, target_date, baseline, status, created_at.

Progress is computed by sampling the relevant data series (weight, lab marker,
workout count, sleep avg, etc.) between baseline and target_date.
"""

from __future__ import annotations

import argparse
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        goals_path,
        load_profile,
        load_snapshot,
        save_profile,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        goals_path,
        load_profile,
        load_snapshot,
        save_profile,
        workspace_lock,
    )


# Recognised metrics → how to compute current value
METRICS = {
    "weight_kg":      "Weight (kg)",
    "ldl":            "LDL cholesterol",
    "hdl":            "HDL cholesterol",
    "a1c":            "A1c",
    "tsh":            "TSH",
    "total_cholesterol": "Total cholesterol",
    "workouts_per_week": "Workouts/week",
    "sleep_avg":      "Avg sleep (h)",
    "mood_avg":       "Avg mood",
    "rhr":            "Resting heart rate",
    "steps_per_day":  "Steps/day",
}


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _next_id(goals: list[dict[str, Any]]) -> str:
    nums = [int(g.get("id", "g0").lstrip("g")) for g in goals if str(g.get("id", "")).startswith("g")]
    return f"g{max(nums) + 1 if nums else 1}"


def add_goal(
    root: Path,
    person_id: str,
    title: str,
    metric: str,
    target: float,
    unit: str = "",
    target_date: str = "",
    direction: str = "down",
) -> dict[str, Any]:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric '{metric}'. Choose from: {', '.join(METRICS)}")
    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        goals = list(profile.get("goals", []))
        goal = {
            "id": _next_id(goals),
            "title": title,
            "metric": metric,
            "target": target,
            "unit": unit,
            "target_date": target_date,
            "direction": direction,  # "down" (e.g. weight, LDL) or "up" (e.g. workouts)
            "status": "active",
            "created_at": date.today().isoformat(),
        }
        # Capture baseline now
        baseline = current_value(root, person_id, metric)
        if baseline is not None:
            goal["baseline"] = baseline
        goals.append(goal)
        profile["goals"] = goals
        save_profile(root, person_id, profile)
    return goal


def current_value(root: Path, person_id: str, metric: str) -> float | None:
    """Return the most recent value for a metric, or None."""
    snap = load_snapshot(root, person_id)
    p = snap.profile
    if metric == "weight_kg":
        if snap.weight_entries:
            return float(snap.weight_entries[-1]["value"])
        return None
    if metric in ("ldl", "hdl", "a1c", "tsh", "total_cholesterol"):
        target_name = {"ldl": "LDL", "hdl": "HDL", "a1c": "A1C", "tsh": "TSH", "total_cholesterol": "Total Cholesterol"}[metric]
        candidates = [t for t in p.get("recent_tests", []) if str(t.get("name", "")).upper() == target_name.upper()]
        candidates.sort(key=lambda t: str(t.get("date", "")))
        if candidates:
            try:
                return float(candidates[-1].get("value"))
            except (TypeError, ValueError):
                return None
        return None
    if metric == "workouts_per_week":
        cutoff = date.today() - timedelta(days=28)
        recent = [w for w in p.get("workouts", [])
                  if (_parse_date(w.get("date", "")) or date(1900, 1, 1)) >= cutoff]
        return len(recent) / 4.0 if recent else 0.0
    if metric == "sleep_avg":
        cutoff = date.today() - timedelta(days=14)
        sleeps = [float(c["sleep_hours"]) for c in p.get("daily_checkins", [])
                  if isinstance(c.get("sleep_hours"), (int, float))
                  and (_parse_date(c.get("date", "")) or date(1900, 1, 1)) >= cutoff]
        return statistics.mean(sleeps) if sleeps else None
    if metric == "mood_avg":
        cutoff = date.today() - timedelta(days=14)
        moods = [float(c["mood"]) for c in p.get("daily_checkins", [])
                 if isinstance(c.get("mood"), (int, float))
                 and (_parse_date(c.get("date", "")) or date(1900, 1, 1)) >= cutoff]
        return statistics.mean(moods) if moods else None
    if metric == "rhr":
        rhrs = [float(v["numeric_value"]) for v in snap.vital_entries
                if v.get("metric") == "heart_rate" and v.get("numeric_value") is not None]
        return rhrs[-1] if rhrs else None
    if metric == "steps_per_day":
        cutoff = date.today() - timedelta(days=14)
        steps = [float(v["numeric_value"]) for v in snap.vital_entries
                 if v.get("metric") == "steps" and v.get("numeric_value") is not None
                 and (_parse_date(v.get("entry_date", "")) or date(1900, 1, 1)) >= cutoff]
        return statistics.mean(steps) if steps else None
    return None


def progress_pct(goal: dict[str, Any], current: float | None) -> float | None:
    """0–100 (or >100 if exceeded). None if no baseline or current."""
    if current is None or "baseline" not in goal:
        return None
    baseline = float(goal["baseline"])
    target = float(goal["target"])
    if baseline == target:
        return 100.0 if current == target else 0.0
    return round(((current - baseline) / (target - baseline)) * 100.0, 1)


def render_goals_md(root: Path, person_id: str) -> str:
    profile = load_profile(root, person_id)
    goals = profile.get("goals", [])
    today = date.today()
    lines = ["# Goals\n"]
    if not goals:
        lines.append("No goals set yet.")
        lines.append("")
        lines.append("Add one with:")
        lines.append("```")
        lines.append("scripts/care_workspace.py add-goal --root . \\")
        lines.append('  --title "LDL under 130" --metric ldl --target 130 --unit mg/dL --direction down')
        lines.append("```")
        return "\n".join(lines) + "\n"

    for g in goals:
        if g.get("status") not in (None, "active", "achieved"):
            continue
        cur = current_value(root, person_id, g["metric"])
        pct = progress_pct(g, cur)
        bar_len = 20
        filled = int((min(pct, 100) / 100) * bar_len) if pct is not None else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"## {g['title']}")
        lines.append("")
        lines.append(f"- Metric: {METRICS.get(g['metric'], g['metric'])}")
        baseline_str = f"{g.get('baseline', '?')}" if g.get("baseline") is not None else "?"
        cur_str = f"{cur:.1f}" if isinstance(cur, (int, float)) else "?"
        lines.append(f"- Baseline → Now → Target: {baseline_str} → **{cur_str}** → {g['target']} {g.get('unit', '')}")
        if g.get("target_date"):
            d = _parse_date(g["target_date"])
            if d:
                days = (d - today).days
                lines.append(f"- Target date: {g['target_date']} ({days} days {'remaining' if days >= 0 else 'overdue'})")
        if pct is not None:
            lines.append(f"- Progress: `{bar}` {pct:.0f}%")
        lines.append("")
    lines.append(f"_Generated {today.isoformat()}_")
    return "\n".join(lines) + "\n"


def write_goals(root: Path, person_id: str) -> Path:
    text = render_goals_md(root, person_id)
    path = goals_path(root, person_id)
    atomic_write_text(path, text)
    return path
