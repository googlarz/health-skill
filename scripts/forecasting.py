#!/usr/bin/env python3
"""Forecasting engine — project labs, weight, vitals into the future.

Pure stdlib least-squares linear regression on time-series data. Not magical
ML — explicit, debuggable, with confidence intervals and clear "we don't have
enough data" guards.

Output: HEALTH_FORECAST.md with projections + plain-language interpretation.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        forecast_path,
        load_snapshot,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        forecast_path,
        load_snapshot,
    )


MIN_POINTS = 3  # need at least 3 to project
KEY_LAB_MARKERS = ["LDL", "HDL", "A1C", "TSH", "Total Cholesterol",
                   "Triglycerides", "Vitamin D", "Glucose", "Creatinine", "ALT"]


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _linear_regression(xs: list[float], ys: list[float]) -> dict[str, float]:
    """Returns slope, intercept, r_squared, std_error of slope."""
    n = len(xs)
    if n < 2:
        return {"slope": 0.0, "intercept": ys[0] if ys else 0.0, "r_squared": 0.0, "std_error": 0.0}
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    intercept = my - slope * mx
    # R²
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    # Std error of slope (for confidence band)
    if n > 2 and den > 0:
        residual_se = math.sqrt(ss_res / (n - 2))
        slope_se = residual_se / math.sqrt(den)
    else:
        slope_se = 0.0
    return {"slope": slope, "intercept": intercept, "r_squared": r_squared, "std_error": slope_se}


def forecast_marker(
    series: list[tuple[date, float]],
    target_value: float | None = None,
    horizon_days: int = 180,
) -> dict[str, Any]:
    """Forecast a single time series.

    Returns:
      {
        slope_per_day, slope_per_year, r_squared, n_points,
        latest_value, latest_date,
        projected_value (at today + horizon_days),
        projected_value_ci_low, projected_value_ci_high,  (95% band)
        days_to_target (if target_value given and trajectory crosses it),
        confidence: "high"|"medium"|"low",
      }
    """
    if len(series) < MIN_POINTS:
        return {"insufficient_data": True, "n_points": len(series)}

    series = sorted(series, key=lambda x: x[0])
    base = series[0][0]
    xs = [(d - base).days for d, _ in series]
    ys = [v for _, v in series]
    fit = _linear_regression([float(x) for x in xs], ys)

    today = date.today()
    today_x = (today - base).days
    horizon_x = today_x + horizon_days

    projected = fit["slope"] * horizon_x + fit["intercept"]
    # 95% CI band (~1.96 * SE * sqrt(n_horizon))
    ci_half = 1.96 * fit["std_error"] * abs(horizon_days)
    ci_low = projected - ci_half
    ci_high = projected + ci_half

    days_to_target: float | None = None
    if target_value is not None and fit["slope"] != 0:
        x_target = (target_value - fit["intercept"]) / fit["slope"]
        days_to_target = x_target - today_x
        if days_to_target < 0 or days_to_target > 365 * 5:
            days_to_target = None  # already past, or too far out

    # Confidence heuristic
    if len(series) >= 6 and fit["r_squared"] >= 0.6:
        confidence = "high"
    elif len(series) >= 4 and fit["r_squared"] >= 0.3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "n_points": len(series),
        "slope_per_day": fit["slope"],
        "slope_per_year": fit["slope"] * 365.0,
        "r_squared": round(fit["r_squared"], 3),
        "latest_value": ys[-1],
        "latest_date": series[-1][0].isoformat(),
        "projected_value": round(projected, 2),
        "projected_value_ci_low": round(ci_low, 2),
        "projected_value_ci_high": round(ci_high, 2),
        "horizon_days": horizon_days,
        "horizon_date": (today + timedelta(days=horizon_days)).isoformat(),
        "days_to_target": int(days_to_target) if days_to_target else None,
        "target_value": target_value,
        "confidence": confidence,
    }


def forecast_labs(profile: dict[str, Any], horizon_days: int = 180) -> dict[str, dict]:
    """Forecast each key lab marker present in the profile."""
    grouped: dict[str, list[tuple[date, float]]] = {}
    for t in profile.get("recent_tests", []):
        name = str(t.get("name", "")).strip()
        d = _parse_date(t.get("date", ""))
        try:
            v = float(t.get("value"))
        except (TypeError, ValueError):
            continue
        if not name or not d:
            continue
        # Match any of the key markers (case-insensitive prefix)
        for marker in KEY_LAB_MARKERS:
            if name.upper() == marker.upper() or name.upper().startswith(marker.upper()):
                grouped.setdefault(marker, []).append((d, v))
                break

    results: dict[str, dict] = {}
    for marker, series in grouped.items():
        results[marker] = forecast_marker(series, horizon_days=horizon_days)
    return results


def forecast_weight(snap_weight_entries: list[dict[str, Any]],
                    target_value: float | None = None,
                    horizon_days: int = 90) -> dict[str, Any]:
    series: list[tuple[date, float]] = []
    for w in snap_weight_entries:
        d = _parse_date(w.get("entry_date", ""))
        try:
            v = float(w.get("value"))
        except (TypeError, ValueError):
            continue
        if d:
            series.append((d, v))
    return forecast_marker(series, target_value=target_value, horizon_days=horizon_days)


def _interpret(marker: str, f: dict[str, Any]) -> str:
    """Plain-language one-liner for a forecast."""
    if f.get("insufficient_data"):
        return f"Need at least {MIN_POINTS} data points to project (have {f.get('n_points', 0)})."
    direction = "↑" if f["slope_per_year"] > 0 else "↓" if f["slope_per_year"] < 0 else "→"
    yr = f["slope_per_year"]
    base = (f"{marker}: latest {f['latest_value']} on {f['latest_date']}. "
            f"Trend {direction} {abs(yr):.1f}/year (R²={f['r_squared']}).")
    if f.get("days_to_target") is not None:
        eta = (date.today() + timedelta(days=f["days_to_target"])).isoformat()
        base += f" At this rate hits {f['target_value']} by ~{eta}."
    return base


def render_forecast_md(profile: dict[str, Any], snap_weight_entries: list[dict[str, Any]]) -> str:
    today = date.today()
    name = profile.get("name") or "You"
    lines = [f"# Health Forecast — {name}", "",
             f"_Generated {today.isoformat()} · Linear projections, not predictions._", ""]

    lab_forecasts = forecast_labs(profile)
    if lab_forecasts:
        lines.append("## Lab projections (next 6 months)")
        lines.append("")
        for marker in sorted(lab_forecasts):
            f = lab_forecasts[marker]
            lines.append(f"### {marker}")
            lines.append("")
            lines.append("- " + _interpret(marker, f))
            if not f.get("insufficient_data"):
                lines.append(f"- Confidence: **{f['confidence']}** ({f['n_points']} data points)")
                lines.append(f"- Projected on {f['horizon_date']}: **{f['projected_value']}** "
                             f"(95% CI: {f['projected_value_ci_low']} – {f['projected_value_ci_high']})")
            lines.append("")
    else:
        lines.append("_Not enough lab data yet. Drop a few lab reports into `inbox/` to enable forecasting._")
        lines.append("")

    # Weight
    if snap_weight_entries:
        wf = forecast_weight(snap_weight_entries, horizon_days=90)
        if not wf.get("insufficient_data"):
            lines.append("## Weight projection (next 90 days)")
            lines.append("")
            lines.append("- " + _interpret("Weight (kg)", wf))
            lines.append(f"- Confidence: **{wf['confidence']}** ({wf['n_points']} entries)")
            lines.append(f"- Projected {wf['horizon_date']}: **{wf['projected_value']} kg** "
                         f"(CI: {wf['projected_value_ci_low']} – {wf['projected_value_ci_high']})")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Important:** These are simple linear projections from your historical data. "
                 "They assume current habits continue and do not predict illness, treatment response, "
                 "or biological complexity. Use as conversation starters with your clinician, not as facts.")
    return "\n".join(lines) + "\n"


def write_forecast(root: Path, person_id: str) -> Path:
    snap = load_snapshot(root, person_id)
    text = render_forecast_md(snap.profile, snap.weight_entries)
    path = forecast_path(root, person_id)
    atomic_write_text(path, text)
    return path
