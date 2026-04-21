#!/usr/bin/env python3
"""Cross-domain pattern engine.

Correlates data across check-ins, cycles, workouts, labs, meds, weight, vitals
to surface high-signal insights to the user.

Design principles:
- Be conservative. Require 5+ data points before surfacing any pattern.
- Always report confidence. Low-confidence findings must say so.
- Avoid clinical claims — suggest discussing with a clinician when relevant.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        load_profile,
        load_vital_entries,
        load_weight_entries,
    )
except ImportError:
    from care_workspace import (
        load_profile,
        load_vital_entries,
        load_weight_entries,
    )


MIN_DATA_POINTS = 5


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _days_ago(d: date, reference: date) -> int:
    return (reference - d).days


def _insight(
    title: str,
    detail: str,
    confidence: str,
    category: str,
    data_points: int,
    date_range: str = "",
    suggested_action: str | None = None,
) -> dict[str, Any]:
    out = {
        "title": title,
        "detail": detail,
        "confidence": confidence,
        "category": category,
        "data_points": data_points,
        "date_range": date_range,
    }
    if suggested_action:
        out["suggested_action"] = suggested_action
    return out


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------

def _detect_pms_mood(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Mood drops 1-5 days before period onset across multiple cycles."""
    cycles = profile.get("cycles", [])
    checkins = profile.get("daily_checkins", [])
    if len(cycles) < 3 or len(checkins) < MIN_DATA_POINTS:
        return None

    checkin_by_date: dict[date, dict[str, Any]] = {}
    for c in checkins:
        d = _parse_date(c.get("date", ""))
        if d:
            checkin_by_date[d] = c

    triggered = 0
    examined = 0
    for cycle in cycles[-4:]:
        start = _parse_date(cycle.get("start_date", ""))
        if not start:
            continue
        examined += 1
        pre_moods = []
        baseline_moods = []
        for offset in range(1, 6):
            ci = checkin_by_date.get(start - timedelta(days=offset))
            if ci and ci.get("mood") is not None:
                try:
                    pre_moods.append(float(ci["mood"]))
                except (TypeError, ValueError):
                    pass
        for offset in range(8, 16):
            ci = checkin_by_date.get(start - timedelta(days=offset))
            if ci and ci.get("mood") is not None:
                try:
                    baseline_moods.append(float(ci["mood"]))
                except (TypeError, ValueError):
                    pass
        if pre_moods and baseline_moods:
            if statistics.mean(pre_moods) <= statistics.mean(baseline_moods) - 1.5:
                triggered += 1

    if examined >= 3 and triggered >= max(2, examined - 1):
        return _insight(
            title="Possible PMS mood pattern",
            detail=f"Your mood scores dropped in the days before period start in {triggered} of last {examined} cycles.",
            confidence="medium" if examined < 4 else "high",
            category="cycle",
            data_points=examined,
            suggested_action="Flag this in your next clinician visit if it affects daily life.",
        )
    return None


def _detect_sleep_pain(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Short sleep days correlate with higher pain reports."""
    checkins = profile.get("daily_checkins", [])
    if len(checkins) < MIN_DATA_POINTS:
        return None

    short_sleep_pain = []
    long_sleep_pain = []
    for c in checkins[-60:]:
        sleep = c.get("sleep") or c.get("sleep_hours")
        pain = c.get("pain")
        if sleep is None or pain is None:
            continue
        try:
            s = float(sleep)
            p = float(pain)
        except (TypeError, ValueError):
            continue
        if s < 6:
            short_sleep_pain.append(p)
        elif s >= 7:
            long_sleep_pain.append(p)

    if len(short_sleep_pain) >= 3 and len(long_sleep_pain) >= 3:
        diff = statistics.mean(short_sleep_pain) - statistics.mean(long_sleep_pain)
        total = len(short_sleep_pain) + len(long_sleep_pain)
        if diff >= 1.5:
            return _insight(
                title="Sleep and pain correlate",
                detail=f"Days with <6h sleep averaged {statistics.mean(short_sleep_pain):.1f}/10 pain vs {statistics.mean(long_sleep_pain):.1f}/10 on 7h+ nights.",
                confidence="medium" if total < 10 else "high",
                category="sleep",
                data_points=total,
                suggested_action="Prioritizing sleep may reduce pain load — experiment for 2 weeks.",
            )
    return None


def _detect_training_gap(profile: dict[str, Any]) -> dict[str, Any] | None:
    workouts = profile.get("workouts", [])
    if not workouts:
        return None
    latest = None
    for w in workouts:
        d = _parse_date(w.get("date", ""))
        if d and (latest is None or d > latest):
            latest = d
    if latest is None:
        return None
    gap = (date.today() - latest).days
    if gap >= 21:
        return _insight(
            title="Training gap detected",
            detail=f"{gap} days since your last logged workout. Has your routine changed?",
            confidence="high",
            category="training",
            data_points=len(workouts),
            date_range=f"last logged: {latest.isoformat()}",
            suggested_action="Want me to help restart with a lighter reintro week?",
        )
    return None


def _detect_rhr_trend(vitals: list[dict[str, Any]]) -> dict[str, Any] | None:
    hrs = [(v, _parse_date(v.get("entry_date", ""))) for v in vitals if v.get("metric") == "heart_rate"]
    hrs = [(float(v["numeric_value"]), d) for v, d in hrs if d and v.get("numeric_value") is not None]
    if len(hrs) < MIN_DATA_POINTS:
        return None
    hrs.sort(key=lambda x: x[1])
    first_third = [h for h, _ in hrs[: len(hrs) // 3 or 1]]
    last_third = [h for h, _ in hrs[-(len(hrs) // 3 or 1):]]
    delta = statistics.mean(last_third) - statistics.mean(first_third)
    start_d = hrs[0][1].isoformat()
    end_d = hrs[-1][1].isoformat()
    if delta <= -5:
        return _insight(
            title="Resting heart rate trending down",
            detail=f"Average RHR moved from {statistics.mean(first_third):.0f} to {statistics.mean(last_third):.0f} bpm.",
            confidence="high" if len(hrs) >= 10 else "medium",
            category="training",
            data_points=len(hrs),
            date_range=f"{start_d} to {end_d}",
            suggested_action="Positive cardiovascular adaptation — keep it up.",
        )
    if delta >= 5:
        return _insight(
            title="Resting heart rate trending up",
            detail=f"Average RHR moved from {statistics.mean(first_third):.0f} to {statistics.mean(last_third):.0f} bpm.",
            confidence="medium",
            category="training",
            data_points=len(hrs),
            date_range=f"{start_d} to {end_d}",
            suggested_action="Could indicate under-recovery, illness, or stress. Worth watching.",
        )
    return None


def _detect_weight_sleep(profile: dict[str, Any], weights: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(weights) < MIN_DATA_POINTS:
        return None
    parsed = [(float(w["value"]), _parse_date(w.get("entry_date", ""))) for w in weights if w.get("value") is not None]
    parsed = [(v, d) for v, d in parsed if d]
    if len(parsed) < MIN_DATA_POINTS:
        return None
    parsed.sort(key=lambda x: x[1])
    cutoff = date.today() - timedelta(days=28)
    recent = [v for v, d in parsed if d >= cutoff]
    older = [v for v, d in parsed if d < cutoff]
    if len(recent) < 2 or len(older) < 2:
        return None
    weight_delta = statistics.mean(recent) - statistics.mean(older)

    # Look at sleep over last 28 days vs prior
    checkins = profile.get("daily_checkins", [])
    rs, os_ = [], []
    for c in checkins:
        d = _parse_date(c.get("date", ""))
        s = c.get("sleep") or c.get("sleep_hours")
        if not d or s is None:
            continue
        try:
            s = float(s)
        except (TypeError, ValueError):
            continue
        (rs if d >= cutoff else os_).append(s)
    if weight_delta >= 1.5 and rs and os_:
        sleep_delta = statistics.mean(rs) - statistics.mean(os_)
        if sleep_delta <= -0.5:
            return _insight(
                title="Weight up while sleep down",
                detail=f"Weight up {weight_delta:.1f} over 4 weeks; sleep down {abs(sleep_delta):.1f}h/night vs prior.",
                confidence="low",
                category="metabolic",
                data_points=len(parsed) + len(rs) + len(os_),
                suggested_action="Stress/sleep/appetite can interact. Low confidence — one of many possible drivers.",
            )
    return None


def _detect_lab_trend_vs_training(profile: dict[str, Any]) -> dict[str, Any] | None:
    """LDL trend vs workout frequency change."""
    tests = [t for t in profile.get("recent_tests", []) if str(t.get("name", "")).upper() == "LDL"]
    if len(tests) < 2:
        return None
    parsed = []
    for t in tests:
        d = _parse_date(t.get("date", ""))
        try:
            v = float(t.get("value"))
        except (TypeError, ValueError):
            continue
        if d:
            parsed.append((v, d))
    if len(parsed) < 2:
        return None
    parsed.sort(key=lambda x: x[1])
    first, last = parsed[0], parsed[-1]
    pct_delta = (last[0] - first[0]) / first[0] * 100 if first[0] else 0

    workouts = profile.get("workouts", [])
    wo_dates = [_parse_date(w.get("date", "")) for w in workouts]
    wo_dates = [d for d in wo_dates if d]
    if not wo_dates:
        return None
    span_days = max((last[1] - first[1]).days, 1)
    recent_wos = sum(1 for d in wo_dates if first[1] <= d <= last[1])
    per_week = recent_wos / max(span_days / 7, 1)

    if pct_delta <= -10 and per_week >= 2:
        return _insight(
            title="LDL dropped as training increased",
            detail=f"LDL went from {first[0]:.0f} to {last[0]:.0f} ({pct_delta:.0f}%), while workouts averaged {per_week:.1f}/week.",
            confidence="low",
            category="metabolic",
            data_points=len(parsed) + recent_wos,
            date_range=f"{first[1].isoformat()} to {last[1].isoformat()}",
            suggested_action="Correlation only — confirm trend with clinician before changing meds.",
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_connections(root: Path, person_id: str) -> list[dict[str, Any]]:
    """Scan all domains and return a list of insights (conservative)."""
    profile = load_profile(root, person_id)
    try:
        weights = load_weight_entries(root, person_id)
    except Exception:
        weights = []
    try:
        vitals = load_vital_entries(root, person_id)
    except Exception:
        vitals = []

    detectors = [
        lambda: _detect_pms_mood(profile),
        lambda: _detect_sleep_pain(profile),
        lambda: _detect_training_gap(profile),
        lambda: _detect_rhr_trend(vitals),
        lambda: _detect_weight_sleep(profile, weights),
        lambda: _detect_lab_trend_vs_training(profile),
    ]

    insights: list[dict[str, Any]] = []
    for d in detectors:
        try:
            result = d()
        except Exception:
            result = None
        if result:
            insights.append(result)
    return insights


def render_connections_text(profile: dict[str, Any], connections: list[dict[str, Any]]) -> str:
    name = profile.get("name") or "you"
    lines = [
        "# Connections",
        "",
        f"Cross-domain patterns detected for {name}.",
        "",
        "_These are statistical hints, not clinical conclusions. Be especially cautious with low-confidence findings._",
        "",
    ]
    if not connections:
        lines.extend([
            "No patterns surfaced yet. This usually means:",
            "- Not enough logged data (need 5+ data points per domain)",
            "- Or no strong signals to report right now",
            "",
            "Try logging daily check-ins and workouts for 2 weeks, then re-run.",
            "",
        ])
        return "\n".join(lines)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for c in connections:
        by_category.setdefault(c["category"], []).append(c)

    category_titles = {
        "cycle": "## Cycle",
        "sleep": "## Sleep",
        "training": "## Training",
        "metabolic": "## Metabolic",
        "mental": "## Mental / Mood",
    }
    for cat, title in category_titles.items():
        items = by_category.get(cat, [])
        if not items:
            continue
        lines.append(title)
        lines.append("")
        for c in items:
            lines.append(f"### {c['title']}  _(confidence: {c['confidence']})_")
            lines.append("")
            lines.append(c["detail"])
            if c.get("date_range"):
                lines.append(f"*Range:* {c['date_range']}")
            lines.append(f"*Data points:* {c['data_points']}")
            if c.get("suggested_action"):
                lines.append(f"> {c['suggested_action']}")
            lines.append("")
    return "\n".join(lines)
