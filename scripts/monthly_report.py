#!/usr/bin/env python3
"""Monthly insight report.

Aggregates the last 30 days across all data domains and produces a one-page
summary with trends, highlights, and one action item.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_profile,
        load_weight_entries,
        load_vital_entries,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_profile,
        load_weight_entries,
        load_vital_entries,
    )

MONTHLY_REPORT_FILENAME = "MONTHLY_REPORT.md"


def monthly_report_path(root: Path, person_id: str) -> Path:
    from pathlib import Path as _Path
    try:
        from .care_workspace import person_dir
    except ImportError:
        from care_workspace import person_dir  # type: ignore
    return person_dir(root, person_id) / MONTHLY_REPORT_FILENAME


def _checkins_in_range(checkins: list[dict], start: date, end: date) -> list[dict]:
    result = []
    for c in checkins:
        try:
            d = datetime.strptime(str(c.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= end:
            result.append(c)
    return result


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    mn, mx = min(values), max(values)
    chars = "▁▂▃▄▅▆▇█"
    if mx == mn:
        return chars[3] * len(values)
    return "".join(chars[int((v - mn) / (mx - mn) * 7)] for v in values)


def _trend_arrow(values: list[float]) -> str:
    if len(values) < 2:
        return "→"
    first_half = values[:len(values) // 2]
    second_half = values[len(values) // 2:]
    a1 = sum(first_half) / len(first_half)
    a2 = sum(second_half) / len(second_half)
    delta = a2 - a1
    if delta > 0.5:
        return "↑"
    if delta < -0.5:
        return "↓"
    return "→"


def build_monthly_report(profile: dict[str, Any], root: Path, person_id: str) -> str:
    today = date.today()
    start = today - timedelta(days=30)
    prev_start = start - timedelta(days=30)

    name = profile.get("name") or "you"
    checkins = profile.get("daily_checkins") or []
    workouts = profile.get("workouts") or []

    month_checkins = _checkins_in_range(checkins, start, today)
    prev_checkins = _checkins_in_range(checkins, prev_start, start)

    lines = [
        f"# Monthly Report — {today.strftime('%B %Y')}",
        "",
        f"_Period: {start.isoformat()} → {today.isoformat()} · {len(month_checkins)} check-ins logged_",
        "",
    ]

    # ── Check-in trends ──────────────────────────────────────────────────────
    if month_checkins:
        lines.append("## Daily check-in trends\n")
        fields = [
            ("mood",        "Mood",    "/ 10"),
            ("energy",      "Energy",  "/ 10"),
            ("pain",        "Pain",    "/ 10"),
            ("sleep_hours", "Sleep",   "h"),
        ]
        highlights: list[str] = []
        for field, label, suffix in fields:
            this_vals = [float(c[field]) for c in month_checkins if c.get(field) is not None]
            prev_vals = [float(c[field]) for c in prev_checkins if c.get(field) is not None]
            if not this_vals:
                continue
            avg = _avg(this_vals)
            prev_avg = _avg(prev_vals)
            spark = _sparkline(this_vals)
            arrow = _trend_arrow(this_vals)
            assert avg is not None
            delta_str = ""
            if prev_avg is not None:
                delta = avg - prev_avg
                if abs(delta) >= 0.3:
                    delta_str = f" ({delta:+.1f} vs prev month)"
            lines.append(f"**{label}** {avg:.1f}{suffix} {arrow}  `{spark}`{delta_str}")

            # Highlight notable changes
            if field == "mood" and prev_avg is not None and avg - prev_avg <= -1.5:
                highlights.append(f"Mood dropped {avg - prev_avg:.1f} points vs last month")
            if field == "sleep_hours" and prev_avg is not None and avg - prev_avg <= -0.5:
                highlights.append(f"Sleep shortened by {abs(avg - prev_avg):.1f}h vs last month")
            if field == "pain" and avg >= 4.0:
                highlights.append(f"Average pain score {avg:.1f}/10 — worth reviewing")

        lines.append("")
        if highlights:
            lines.append("**Notable changes:**")
            for h in highlights:
                lines.append(f"- ⚠️ {h}")
            lines.append("")

    # ── Training ─────────────────────────────────────────────────────────────
    month_workouts = []
    for w in workouts:
        try:
            d = datetime.strptime(str(w.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= today:
            month_workouts.append(w)

    if month_workouts:
        total_min = sum(w.get("duration", 0) or 0 for w in month_workouts)
        by_type: dict[str, int] = {}
        for w in month_workouts:
            t = (w.get("type") or "other").lower()
            by_type[t] = by_type.get(t, 0) + 1
        top_types = sorted(by_type.items(), key=lambda x: -x[1])[:3]
        lines.append("## Training\n")
        lines.append(f"**{len(month_workouts)} sessions** · {total_min} minutes total")
        lines.append(f"Types: {', '.join(f'{t} ×{n}' for t, n in top_types)}")
        lines.append("")

    # ── Weight ───────────────────────────────────────────────────────────────
    try:
        weight_entries = load_weight_entries(root, person_id)
        month_weights = [
            e for e in weight_entries
            if start <= datetime.strptime(str(e.get("date", ""))[:10], "%Y-%m-%d").date() <= today
        ]
        if month_weights:
            weights = [float(e["kg"]) for e in month_weights if e.get("kg")]
            if len(weights) >= 2:
                delta = weights[-1] - weights[0]
                spark = _sparkline(weights)
                lines.append("## Weight\n")
                lines.append(
                    f"**{weights[-1]:.1f} kg** ({delta:+.1f} kg over the month)  `{spark}`"
                )
                lines.append("")
    except Exception:
        pass

    # ── Labs ─────────────────────────────────────────────────────────────────
    tests = profile.get("recent_tests") or []
    month_labs = []
    for t in tests:
        try:
            d = datetime.strptime(str(t.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= today:
            month_labs.append(t)

    if month_labs:
        lines.append("## New labs this month\n")
        for lab in month_labs:
            flag = lab.get("flag", "normal")
            icon = "✅" if flag == "normal" else "⚠️"
            lines.append(
                f"- {icon} **{lab.get('name')}** {lab.get('value')} {lab.get('unit', '')} "
                f"({lab.get('date', '')})"
            )
        lines.append("")

    # ── Action item ──────────────────────────────────────────────────────────
    lines.append("## One thing to do this month\n")
    action = _pick_action(profile, month_checkins, month_workouts, today)
    lines.append(f"→ {action}")
    lines.append("")

    lines.append(
        f"_Generated {today.isoformat()}. "
        "Run `monthly-report` at the start of each month for a fresh view._\n"
    )
    return "\n".join(lines)


def _pick_action(
    profile: dict[str, Any],
    checkins: list[dict],
    workouts: list[dict],
    today: date,
) -> str:
    """Heuristic: pick the single most impactful action."""
    # Overdue labs (>12 months)
    tests = profile.get("recent_tests") or []
    if tests:
        dates = []
        for t in tests:
            try:
                dates.append(datetime.strptime(str(t.get("date", ""))[:10], "%Y-%m-%d").date())
            except ValueError:
                pass
        if dates and (today - max(dates)).days > 365:
            return "Book a blood panel — your last labs are over 12 months old."

    # Low training
    if len(workouts) < 4:
        return f"Aim for at least 8 sessions next month — you logged {len(workouts)} this month."

    # Poor sleep
    sleep_vals = [float(c["sleep_hours"]) for c in checkins if c.get("sleep_hours") is not None]
    if sleep_vals and _avg(sleep_vals) is not None:
        avg_sleep = _avg(sleep_vals)
        assert avg_sleep is not None
        if avg_sleep < 6.5:
            return f"Prioritise sleep — your average was {avg_sleep:.1f}h this month. Aim for 7+."

    # High pain
    pain_vals = [float(c["pain"]) for c in checkins if c.get("pain") is not None]
    if pain_vals:
        avg_pain = _avg(pain_vals)
        assert avg_pain is not None
        if avg_pain >= 4.0:
            return f"Average pain score was {avg_pain:.1f}/10 — consider discussing with your clinician."

    # Low mood
    mood_vals = [float(c["mood"]) for c in checkins if c.get("mood") is not None]
    if mood_vals:
        avg_mood = _avg(mood_vals)
        assert avg_mood is not None
        if avg_mood < 6.0:
            return f"Mood averaged {avg_mood:.1f}/10 — check in with yourself or someone you trust."

    return "Keep going — no urgent gaps detected. Review your goals and adjust targets if needed."


def write_monthly_report(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    text = build_monthly_report(profile, root, person_id)
    path = monthly_report_path(root, person_id)
    atomic_write_text(path, text)
    return path
