#!/usr/bin/env python3
"""Weekly recap generator.

Produces WEEKLY_RECAP.md summarising the last 7 days: check-ins, workouts,
weight, vitals, new documents, and one-line "what to action next".
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_snapshot,
        recap_path,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_snapshot,
        recap_path,
    )


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _trend(values: list[float]) -> str:
    if len(values) < 3:
        return "→"
    first = statistics.mean(values[: len(values) // 2 or 1])
    last = statistics.mean(values[-(len(values) // 2 or 1):])
    delta = last - first
    if delta > 0.5:
        return "↑"
    if delta < -0.5:
        return "↓"
    return "→"


def build_recap(root: Path, person_id: str, days: int = 7) -> str:
    snap = load_snapshot(root, person_id)
    p = snap.profile
    today = date.today()
    cutoff = today - timedelta(days=days)
    name = p.get("name") or "You"

    lines: list[str] = []
    lines.append(f"# Weekly Recap — {name}")
    lines.append("")
    lines.append(f"_Window: {cutoff.isoformat()} → {today.isoformat()}_")
    lines.append("")

    # Check-ins
    checkins = []
    for c in p.get("daily_checkins", []):
        d = _parse_date(c.get("date", ""))
        if d and d >= cutoff:
            checkins.append(c)
    checkins.sort(key=lambda c: str(c.get("date", "")))

    lines.append("## How you've felt")
    lines.append("")
    if checkins:
        moods = [float(c["mood"]) for c in checkins if isinstance(c.get("mood"), (int, float))]
        sleeps = [float(c["sleep_hours"]) for c in checkins if isinstance(c.get("sleep_hours"), (int, float))]
        energies = [float(c["energy"]) for c in checkins if isinstance(c.get("energy"), (int, float))]
        pains = [float(c["pain_severity"]) for c in checkins if isinstance(c.get("pain_severity"), (int, float))]

        if moods:
            lines.append(f"- **Mood**: avg {_mean(moods):.1f}/10 {_trend(moods)} ({len(moods)} entries)")
        if sleeps:
            lines.append(f"- **Sleep**: avg {_mean(sleeps):.1f}h {_trend(sleeps)} ({len(sleeps)} nights)")
        if energies:
            lines.append(f"- **Energy**: avg {_mean(energies):.1f}/10 {_trend(energies)}")
        if pains:
            lines.append(f"- **Pain**: avg {_mean(pains):.1f}/10 {_trend(pains)}")
        if not (moods or sleeps or energies or pains):
            lines.append(f"- {len(checkins)} check-in(s) logged but no scored fields.")
    else:
        lines.append("- No check-ins this week. Try one — even one line a day reveals patterns.")
    lines.append("")

    # Workouts
    lines.append("## Training")
    lines.append("")
    workouts = []
    for w in p.get("workouts", []):
        d = _parse_date(w.get("date", ""))
        if d and d >= cutoff:
            workouts.append(w)
    if workouts:
        total_min = sum(int(w.get("duration_min") or w.get("duration_minutes") or 0) for w in workouts)
        types = sorted({str(w.get("type", "workout")) for w in workouts})
        lines.append(f"- **{len(workouts)} session(s)** · {total_min} total minutes")
        lines.append(f"- Types: {', '.join(types)}")
    else:
        lines.append("- No workouts logged this week.")
    lines.append("")

    # Weight
    lines.append("## Weight")
    lines.append("")
    weights = sorted(
        [(w["entry_date"], float(w["value"])) for w in snap.weight_entries if _parse_date(w.get("entry_date", "")) and _parse_date(w["entry_date"]) >= cutoff],
        key=lambda x: x[0],
    )
    if len(weights) >= 2:
        delta = weights[-1][1] - weights[0][1]
        sign = "+" if delta >= 0 else ""
        lines.append(f"- {weights[0][1]:.1f} kg → {weights[-1][1]:.1f} kg ({sign}{delta:.1f} kg)")
    elif weights:
        lines.append(f"- {weights[0][1]:.1f} kg ({weights[0][0]})")
    else:
        lines.append("- No weight logged this week.")
    lines.append("")

    # New documents
    lines.append("## What I processed")
    lines.append("")
    docs = []
    for d in p.get("documents", []):
        dt = _parse_date(d.get("ingested_at", "")[:10])
        if dt and dt >= cutoff:
            docs.append(d)
    if docs:
        for d in docs[:5]:
            lines.append(f"- {d.get('label', d.get('filename', 'document'))} ({d.get('document_type', '')})")
    else:
        lines.append("- No new documents this week.")
    lines.append("")

    # Action next
    lines.append("## One thing to action next")
    lines.append("")
    overdue = [f for f in p.get("follow_ups", [])
               if f.get("status") != "completed" and _parse_date(f.get("due_date", ""))
               and (_parse_date(f["due_date"]) or today) < today]  # type: ignore[operator]
    open_reviews = [r for r in snap.review_queue if r.get("status") == "open"]
    if overdue:
        lines.append(f"- **Overdue:** {overdue[0].get('task', 'follow-up')} (was due {overdue[0].get('due_date', '?')}).")
    elif open_reviews:
        lines.append(f"- Confirm {len(open_reviews)} pending extracted item(s) in REVIEW_WORKLIST.md.")
    elif not checkins:
        lines.append("- Log one check-in. Try: `mood 7, slept 7h, energy 6`")
    else:
        lines.append("- Nothing on fire. Keep the streak going.")
    lines.append("")

    lines.append(f"_Generated {today.isoformat()}_")
    return "\n".join(lines) + "\n"


def write_recap(root: Path, person_id: str, days: int = 7) -> Path:
    text = build_recap(root, person_id, days=days)
    path = recap_path(root, person_id)
    atomic_write_text(path, text)
    return path
