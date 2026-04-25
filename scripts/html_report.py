#!/usr/bin/env python3
"""HTML artifact generator for Health Skill.

Produces a single self-contained HTML file with Chart.js visualisations:
- Overview cards (mood, energy, sleep, pain averages)
- Daily trends chart (mood / energy / sleep / pain over last 90 days)
- Weight timeline
- Lab results vs. personalised reference ranges
- Medication timeline
- Mental health trend (PHQ-2 proxy rolling)
- Upcoming appointments
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_html_report(profile: dict[str, Any]) -> str:
    """Return a fully self-contained HTML string."""
    name = profile.get("name", "Health Dashboard")
    generated = date.today().isoformat()

    checkins = _sorted_checkins(profile)
    weight_entries = _sorted_weight(profile)
    labs = profile.get("lab_results", [])
    meds = profile.get("medications", [])
    appointments = profile.get("appointments", [])
    conditions = profile.get("conditions", [])

    # Pre-compute data for charts
    trend_data = _trend_chart_data(checkins, days=90)
    weight_data = _weight_chart_data(weight_entries, days=180)
    lab_chart = _lab_chart_data(labs, profile)
    med_timeline = _medication_timeline(meds)
    overview = _overview_cards(checkins)
    upcoming_appts = _upcoming_appointments(appointments)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} — Health Report</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f1117; --surface: #1a1d27; --surface2: #232637;
      --accent: #6c8fef; --accent2: #5dd6a8; --accent3: #f5a623;
      --text: #e2e8f0; --muted: #8892a4; --danger: #f87171; --border: #2d3148;
    }}
    body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px; min-height: 100vh; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
    h2 {{ font-size: 1rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 16px; }}
    .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 32px; }}
    .grid {{ display: grid; gap: 20px; }}
    .grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
    .grid-2 {{ grid-template-columns: repeat(2, 1fr); }}
    .grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
    @media (max-width: 900px) {{ .grid-4 {{ grid-template-columns: repeat(2, 1fr); }} .grid-2, .grid-3 {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 480px) {{ .grid-4 {{ grid-template-columns: 1fr 1fr; }} }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
    .card-chart {{ padding: 20px 20px 12px; }}
    .kpi-value {{ font-size: 2.4rem; font-weight: 800; line-height: 1; }}
    .kpi-label {{ color: var(--muted); font-size: 0.8rem; margin-top: 6px; }}
    .kpi-delta {{ font-size: 0.78rem; margin-top: 4px; }}
    .delta-up {{ color: var(--accent2); }} .delta-down {{ color: var(--danger); }} .delta-flat {{ color: var(--muted); }}
    .chart-wrap {{ position: relative; height: 260px; }}
    .chart-wrap-sm {{ position: relative; height: 200px; }}
    .section {{ margin-bottom: 32px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th {{ color: var(--muted); font-weight: 500; text-align: left; padding: 6px 12px; border-bottom: 1px solid var(--border); }}
    td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
    tr:last-child td {{ border-bottom: none; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.72rem; font-weight: 600; }}
    .badge-green {{ background: rgba(93,214,168,.18); color: var(--accent2); }}
    .badge-yellow {{ background: rgba(245,166,35,.18); color: var(--accent3); }}
    .badge-red {{ background: rgba(248,113,113,.18); color: var(--danger); }}
    .badge-blue {{ background: rgba(108,143,239,.18); color: var(--accent); }}
    .badge-gray {{ background: var(--surface2); color: var(--muted); }}
    .appt-row {{ display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }}
    .appt-row:last-child {{ border-bottom: none; }}
    .appt-date {{ font-size: 0.75rem; color: var(--muted); min-width: 90px; }}
    .appt-name {{ font-size: 0.88rem; font-weight: 500; }}
    .appt-reason {{ font-size: 0.78rem; color: var(--muted); }}
    .empty {{ color: var(--muted); font-size: 0.85rem; padding: 12px 0; }}
    .med-bar {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 0.82rem; }}
    .med-line {{ height: 8px; border-radius: 4px; background: var(--accent); opacity: 0.7; min-width: 4px; }}
    footer {{ margin-top: 40px; color: var(--muted); font-size: 0.75rem; text-align: center; }}
  </style>
</head>
<body>

<div class="section">
  <h1>{name}</h1>
  <p class="subtitle">Health report · Generated {generated} · Data covers your full profile history</p>
</div>

<!-- Overview KPI cards -->
<div class="section">
  <h2>30-day averages</h2>
  <div class="grid grid-4">
    {_kpi_card("Mood", overview["mood"], "/10", overview["mood_delta"], "#6c8fef")}
    {_kpi_card("Energy", overview["energy"], "/10", overview["energy_delta"], "#5dd6a8")}
    {_kpi_card("Sleep", overview["sleep"], "h", overview["sleep_delta"], "#c084fc")}
    {_kpi_card("Pain", overview["pain"], "/10", overview["pain_delta"], "#f87171", invert=True)}
  </div>
</div>

<!-- Daily trends chart -->
<div class="section">
  <h2>Daily trends (last 90 days)</h2>
  <div class="card card-chart">
    <div class="chart-wrap">
      <canvas id="trendsChart"></canvas>
    </div>
  </div>
</div>

<!-- Weight + Labs side by side -->
<div class="section grid grid-2">
  <div>
    <h2>Weight timeline</h2>
    <div class="card card-chart">
      <div class="chart-wrap-sm">
        <canvas id="weightChart"></canvas>
      </div>
    </div>
  </div>
  <div>
    <h2>Lab results vs. range</h2>
    <div class="card card-chart">
      <div class="chart-wrap-sm">
        <canvas id="labChart"></canvas>
      </div>
    </div>
  </div>
</div>

<!-- Medications + Appointments side by side -->
<div class="section grid grid-2">
  <div>
    <h2>Active medications</h2>
    <div class="card">
      {_medications_html(meds)}
    </div>
  </div>
  <div>
    <h2>Upcoming appointments</h2>
    <div class="card">
      {_appointments_html(upcoming_appts)}
    </div>
  </div>
</div>

<!-- Conditions -->
{_conditions_html(conditions)}

<footer>Generated by health-skill · Data stays on your device · Not medical advice</footer>

<script>
const CHART_DEFAULTS = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ labels: {{ color: '#8892a4', font: {{ size: 11 }} }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#8892a4', maxRotation: 0, maxTicksLimit: 8 }}, grid: {{ color: '#2d3148' }} }},
    y: {{ ticks: {{ color: '#8892a4' }}, grid: {{ color: '#2d3148' }} }}
  }}
}};

// Trends chart
(function() {{
  const data = {json.dumps(trend_data)};
  if (!data.labels.length) return;
  new Chart(document.getElementById('trendsChart'), {{
    type: 'line',
    data: {{
      labels: data.labels,
      datasets: [
        {{ label: 'Mood', data: data.mood, borderColor: '#6c8fef', backgroundColor: 'rgba(108,143,239,.08)', tension: 0.35, pointRadius: 0, borderWidth: 2 }},
        {{ label: 'Energy', data: data.energy, borderColor: '#5dd6a8', backgroundColor: 'rgba(93,214,168,.06)', tension: 0.35, pointRadius: 0, borderWidth: 2 }},
        {{ label: 'Sleep (h)', data: data.sleep, borderColor: '#c084fc', backgroundColor: 'rgba(192,132,252,.06)', tension: 0.35, pointRadius: 0, borderWidth: 2, yAxisID: 'y2' }},
        {{ label: 'Pain', data: data.pain, borderColor: '#f87171', backgroundColor: 'rgba(248,113,113,.06)', tension: 0.35, pointRadius: 0, borderWidth: 2 }},
      ]
    }},
    options: {{
      ...CHART_DEFAULTS,
      scales: {{
        x: CHART_DEFAULTS.scales.x,
        y: {{ ...CHART_DEFAULTS.scales.y, min: 0, max: 10, title: {{ display: true, text: 'Score /10', color: '#8892a4', font: {{ size: 10 }} }} }},
        y2: {{ ...CHART_DEFAULTS.scales.y, position: 'right', min: 0, max: 12, title: {{ display: true, text: 'Sleep (h)', color: '#8892a4', font: {{ size: 10 }} }}, grid: {{ drawOnChartArea: false }} }}
      }}
    }}
  }});
}})();

// Weight chart
(function() {{
  const data = {json.dumps(weight_data)};
  if (!data.labels.length) {{ document.getElementById('weightChart').parentElement.innerHTML = '<p class=\"empty\">No weight data yet.</p>'; return; }}
  new Chart(document.getElementById('weightChart'), {{
    type: 'line',
    data: {{
      labels: data.labels,
      datasets: [{{ label: 'Weight', data: data.values, borderColor: '#f5a623', backgroundColor: 'rgba(245,166,35,.1)', tension: 0.3, pointRadius: 2, borderWidth: 2, fill: true }}]
    }},
    options: {{
      ...CHART_DEFAULTS,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: CHART_DEFAULTS.scales.x,
        y: {{ ...CHART_DEFAULTS.scales.y, title: {{ display: true, text: data.unit || 'kg', color: '#8892a4', font: {{ size: 10 }} }} }}
      }}
    }}
  }});
}})();

// Lab chart
(function() {{
  const data = {json.dumps(lab_chart)};
  if (!data.labels.length) {{ document.getElementById('labChart').parentElement.innerHTML = '<p class=\"empty\">No lab results yet.</p>'; return; }}
  new Chart(document.getElementById('labChart'), {{
    type: 'bar',
    data: {{
      labels: data.labels,
      datasets: [
        {{ label: 'Your value', data: data.values, backgroundColor: data.colors, borderRadius: 4 }},
      ]
    }},
    options: {{
      ...CHART_DEFAULTS,
      indexAxis: 'y',
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ afterLabel: (ctx) => data.ranges[ctx.dataIndex] }} }} }},
      scales: {{
        x: {{ ...CHART_DEFAULTS.scales.x, title: {{ display: false }} }},
        y: {{ ...CHART_DEFAULTS.scales.y, ticks: {{ color: '#e2e8f0', font: {{ size: 11 }} }} }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>"""
    return html


def write_html_report(root: Path, person_id: str, profile: dict[str, Any]) -> Path:
    """Write HTML report to the person's folder. Returns the output path."""
    from pathlib import Path as P
    out_dir = P(root) / (person_id or "")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "HEALTH_DASHBOARD.html"
    html = build_html_report(profile)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _sorted_checkins(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(profile.get("daily_checkins", []), key=lambda c: c.get("date", ""))


def _sorted_weight(profile: dict[str, Any]) -> list[dict[str, Any]]:
    entries = profile.get("weight_entries", [])
    if not entries:
        return []
    return sorted(entries, key=lambda e: e.get("date", ""))


def _trend_chart_data(checkins: list[dict[str, Any]], days: int = 90) -> dict[str, Any]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [c for c in checkins if c.get("date", "") >= cutoff]
    labels, mood, energy, sleep, pain = [], [], [], [], []
    for c in recent:
        labels.append(c["date"][5:])   # MM-DD
        mood.append(c.get("mood") or None)
        energy.append(c.get("energy") or None)
        sleep.append(c.get("sleep_hours") or None)
        pain.append(c.get("pain") or None)
    return {"labels": labels, "mood": mood, "energy": energy, "sleep": sleep, "pain": pain}


def _weight_chart_data(entries: list[dict[str, Any]], days: int = 180) -> dict[str, Any]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [e for e in entries if e.get("date", "") >= cutoff]
    labels = [e["date"][5:] for e in recent]
    values = [e.get("value") or e.get("weight") for e in recent]
    unit = recent[0].get("unit", "kg") if recent else "kg"
    return {"labels": labels, "values": values, "unit": unit}


def _lab_chart_data(labs: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    """Build horizontal bar data for most recent lab results vs. reference range."""
    try:
        try:
            from .lab_ranges import personalised_range, flag_lab_value
        except ImportError:
            from lab_ranges import personalised_range, flag_lab_value  # type: ignore
    except Exception:
        return {"labels": [], "values": [], "colors": [], "ranges": []}

    # Deduplicate: keep most recent value per marker
    seen: dict[str, dict[str, Any]] = {}
    for entry in sorted(labs, key=lambda x: x.get("date", "")):
        marker = entry.get("marker", "")
        if marker:
            seen[marker] = entry

    labels, values, colors, ranges = [], [], [], []
    for marker, entry in list(seen.items())[:10]:  # cap at 10 for readability
        raw = entry.get("value")
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue

        r = personalised_range(marker, profile)
        flag = flag_lab_value(marker, val, profile)
        color_map = {
            "high": "rgba(248,113,113,0.8)",
            "low": "rgba(248,113,113,0.8)",
            "normal": "rgba(93,214,168,0.8)",
            "optimal": "rgba(108,143,239,0.8)",
        }
        low = r.get("low")
        high = r.get("high")
        range_str = ""
        if low is not None and high is not None:
            range_str = f"Range: {low}–{high} {r.get('unit', '')}"
        elif high is not None:
            range_str = f"Range: <{high} {r.get('unit', '')}"

        labels.append(f"{marker}")
        values.append(val)
        colors.append(color_map.get(flag, "rgba(108,143,239,0.8)"))
        ranges.append(range_str)

    return {"labels": labels, "values": values, "colors": colors, "ranges": ranges}


def _overview_cards(checkins: list[dict[str, Any]]) -> dict[str, Any]:
    def avg(key: str, subset: list) -> float | None:
        vals = [c.get(key) for c in subset if c.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    today = date.today()
    last30 = [c for c in checkins if c.get("date", "") >= (today - timedelta(days=30)).isoformat()]
    prev30 = [c for c in checkins if
               (today - timedelta(days=60)).isoformat() <= c.get("date", "") < (today - timedelta(days=30)).isoformat()]

    result: dict[str, Any] = {}
    for key in ("mood", "energy", "sleep_hours", "pain"):
        out_key = "sleep" if key == "sleep_hours" else key
        cur = avg(key, last30)
        prev = avg(key, prev30)
        result[out_key] = cur
        if cur is not None and prev is not None:
            delta = round(cur - prev, 1)
            result[f"{out_key}_delta"] = delta
        else:
            result[f"{out_key}_delta"] = None
    return result


def _upcoming_appointments(appointments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=90)).isoformat()
    upcoming = [a for a in appointments if today <= a.get("date", "") <= cutoff]
    return sorted(upcoming, key=lambda a: a["date"])[:6]


def _medication_timeline(meds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [m for m in meds if m.get("active", True)]
    return active


# ---------------------------------------------------------------------------
# HTML fragment builders
# ---------------------------------------------------------------------------

def _kpi_card(label: str, value: float | None, suffix: str, delta: float | None,
              color: str, invert: bool = False) -> str:
    val_str = str(value) if value is not None else "—"
    delta_html = ""
    if delta is not None:
        # For pain, going down is good (invert)
        is_good = (delta > 0) if not invert else (delta < 0)
        is_bad = (delta < 0) if not invert else (delta > 0)
        cls = "delta-up" if is_good else ("delta-down" if is_bad else "delta-flat")
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        sign = "+" if delta > 0 else ""
        delta_html = f'<div class="kpi-delta {cls}">{arrow} {sign}{delta} vs prev 30d</div>'
    return f"""
    <div class="card">
      <div class="kpi-value" style="color:{color}">{val_str}<span style="font-size:1rem;font-weight:400;color:#8892a4">{suffix}</span></div>
      <div class="kpi-label">{label}</div>
      {delta_html}
    </div>"""


def _medications_html(meds: list[dict[str, Any]]) -> str:
    active = [m for m in meds if m.get("active", True)]
    if not active:
        return '<p class="empty">No medications recorded.</p>'
    rows = []
    today = date.today().isoformat()
    for m in active:
        name = m.get("name", "Unknown")
        dose = m.get("dose", "")
        freq = m.get("frequency", "")
        start = m.get("start_date", "")
        detail = " · ".join(filter(None, [dose, freq]))
        # Duration
        dur = ""
        if start:
            try:
                days = (date.today() - date.fromisoformat(start)).days
                if days < 7:
                    dur = f"{days}d"
                elif days < 60:
                    dur = f"{days // 7}w"
                else:
                    dur = f"{days // 30}mo"
            except ValueError:
                pass
        rows.append(f"""
        <div class="med-bar">
          <div class="med-line" style="width:{min(100, max(8, len(name)*4))}px"></div>
          <div>
            <div style="font-weight:600">{name}</div>
            <div style="color:var(--muted);font-size:0.75rem">{detail}{(' · ' + dur + ' so far') if dur else ''}</div>
          </div>
        </div>""")
    return "".join(rows)


def _appointments_html(appts: list[dict[str, Any]]) -> str:
    if not appts:
        return '<p class="empty">No upcoming appointments in the next 90 days.</p>'
    rows = []
    today = date.today()
    for a in appts:
        spec = a.get("specialty", "Appointment")
        reason = a.get("reason", "")
        d = a.get("date", "")
        try:
            days_until = (date.fromisoformat(d) - today).days
            if days_until == 0:
                badge = '<span class="badge badge-red">Today</span>'
            elif days_until <= 3:
                badge = f'<span class="badge badge-yellow">In {days_until}d</span>'
            elif days_until <= 14:
                badge = f'<span class="badge badge-blue">In {days_until}d</span>'
            else:
                badge = f'<span class="badge badge-gray">{d}</span>'
        except ValueError:
            badge = f'<span class="badge badge-gray">{d}</span>'
        rows.append(f"""
        <div class="appt-row">
          <div class="appt-date">{badge}</div>
          <div>
            <div class="appt-name">{spec.title()}</div>
            {f'<div class="appt-reason">{reason}</div>' if reason else ''}
          </div>
        </div>""")
    return "".join(rows)


def _conditions_html(conditions: list[dict[str, Any]]) -> str:
    if not conditions:
        return ""
    badges = []
    for c in conditions:
        name = c.get("name", "")
        since = c.get("diagnosed", "")
        tip = f' title="Diagnosed {since}"' if since else ""
        badges.append(f'<span class="badge badge-blue"{tip}>{name}</span>')
    badges_html = " ".join(badges)
    return f"""
<div class="section">
  <h2>Conditions</h2>
  <div class="card" style="display:flex;flex-wrap:wrap;gap:8px;padding:16px">
    {badges_html}
  </div>
</div>"""
