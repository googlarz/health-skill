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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #f7f8fc;
      --surface: #ffffff;
      --surface2: #f0f2f8;
      --border: #e4e7f0;
      --text: #1a1d2e;
      --text2: #4b5168;
      --muted: #8b91a8;
      --blue: #4f6ef7;
      --blue-light: #eef1fe;
      --green: #16a34a;
      --green-light: #dcfce7;
      --red: #dc2626;
      --red-light: #fee2e2;
      --amber: #d97706;
      --amber-light: #fef3c7;
      --purple: #7c3aed;
      --purple-light: #ede9fe;
      --teal: #0d9488;
      --teal-light: #ccfbf1;
    }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }}
    /* ── Layout ── */
    .page {{ max-width: 1120px; margin: 0 auto; padding: 40px 24px 64px; }}
    .grid {{ display: grid; gap: 20px; }}
    .grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
    .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    @media (max-width: 960px) {{
      .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
      .grid-2 {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 480px) {{
      .grid-4 {{ grid-template-columns: 1fr 1fr; }}
    }}
    /* ── Header ── */
    .header {{ margin-bottom: 40px; }}
    .header-top {{ display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
    .header h1 {{ font-size: 1.75rem; font-weight: 800; color: var(--text); letter-spacing: -0.02em; }}
    .header .date-badge {{
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--blue-light); color: var(--blue);
      padding: 6px 14px; border-radius: 99px; font-size: 0.78rem; font-weight: 600;
    }}
    .header .subtitle {{ margin-top: 6px; color: var(--muted); font-size: 0.84rem; }}
    /* ── Section labels ── */
    .section {{ margin-bottom: 36px; }}
    .section-label {{
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--muted); margin-bottom: 14px;
    }}
    /* ── Cards ── */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.03);
    }}
    .card-chart {{ padding: 24px 24px 16px; }}
    /* ── KPI cards ── */
    .kpi-icon {{
      width: 40px; height: 40px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 1.2rem; margin-bottom: 14px;
    }}
    .kpi-value {{
      font-size: 2.2rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1;
    }}
    .kpi-suffix {{ font-size: 0.95rem; font-weight: 500; color: var(--muted); margin-left: 2px; }}
    .kpi-label {{ font-size: 0.8rem; font-weight: 500; color: var(--text2); margin-top: 6px; }}
    .kpi-delta {{
      display: inline-flex; align-items: center; gap: 3px;
      font-size: 0.72rem; font-weight: 600; margin-top: 8px;
      padding: 3px 8px; border-radius: 99px;
    }}
    .delta-up {{ background: var(--green-light); color: var(--green); }}
    .delta-down {{ background: var(--red-light); color: var(--red); }}
    .delta-neutral {{ background: var(--surface2); color: var(--muted); }}
    /* ── Chart wraps ── */
    .chart-wrap {{ position: relative; height: 280px; }}
    .chart-wrap-sm {{ position: relative; height: 220px; }}
    /* ── Chart header (title + legend in card) ── */
    .chart-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 8px; }}
    .chart-title {{ font-size: 0.88rem; font-weight: 600; color: var(--text); }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 0.72rem; color: var(--text2); font-weight: 500; }}
    .legend-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    /* ── List rows ── */
    .row {{ display: flex; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--border); }}
    .row:last-child {{ border-bottom: none; }}
    .row:first-child {{ padding-top: 0; }}
    /* ── Medications ── */
    .med-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--blue); flex-shrink: 0; }}
    .med-name {{ font-size: 0.88rem; font-weight: 600; color: var(--text); }}
    .med-detail {{ font-size: 0.75rem; color: var(--muted); margin-top: 1px; }}
    .med-dur {{
      margin-left: auto; font-size: 0.72rem; font-weight: 600;
      background: var(--surface2); color: var(--text2);
      padding: 3px 8px; border-radius: 99px; white-space: nowrap;
    }}
    /* ── Appointments ── */
    .appt-col {{ display: flex; flex-direction: column; }}
    .appt-name {{ font-size: 0.88rem; font-weight: 600; }}
    .appt-reason {{ font-size: 0.75rem; color: var(--muted); margin-top: 1px; }}
    /* ── Badges ── */
    .badge {{
      display: inline-flex; align-items: center;
      padding: 3px 10px; border-radius: 99px;
      font-size: 0.72rem; font-weight: 600; white-space: nowrap;
    }}
    .badge-red    {{ background: var(--red-light);    color: var(--red);    }}
    .badge-amber  {{ background: var(--amber-light);  color: var(--amber);  }}
    .badge-blue   {{ background: var(--blue-light);   color: var(--blue);   }}
    .badge-green  {{ background: var(--green-light);  color: var(--green);  }}
    .badge-gray   {{ background: var(--surface2);     color: var(--muted);  }}
    .badge-purple {{ background: var(--purple-light); color: var(--purple); }}
    /* ── Condition chips ── */
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; padding-top: 4px; }}
    .chip {{
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--blue-light); color: var(--blue);
      border: 1px solid rgba(79,110,247,.15);
      padding: 5px 12px; border-radius: 8px;
      font-size: 0.8rem; font-weight: 500;
    }}
    /* ── Empty state ── */
    .empty {{ color: var(--muted); font-size: 0.84rem; padding: 8px 0; }}
    /* ── Footer ── */
    footer {{
      margin-top: 48px;
      padding-top: 24px;
      border-top: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;
      color: var(--muted); font-size: 0.75rem;
    }}
    footer strong {{ color: var(--text2); }}
    .footer-note {{ display: flex; align-items: center; gap: 5px; }}
  </style>
</head>
<body>
<div class="page">

<!-- Header -->
<div class="header">
  <div class="header-top">
    <h1>{name}</h1>
    <span class="date-badge">📅 Generated {generated}</span>
  </div>
  <p class="subtitle">Personal health overview · All data stays on your device</p>
</div>

<!-- KPI cards -->
<div class="section">
  <div class="section-label">30-day averages</div>
  <div class="grid grid-4">
    {_kpi_card("Mood", overview["mood"], "/10", overview["mood_delta"], "😊", "#4f6ef7", "#eef1fe")}
    {_kpi_card("Energy", overview["energy"], "/10", overview["energy_delta"], "⚡", "#0d9488", "#ccfbf1")}
    {_kpi_card("Sleep", overview["sleep"], "h", overview["sleep_delta"], "🌙", "#7c3aed", "#ede9fe")}
    {_kpi_card("Pain", overview["pain"], "/10", overview["pain_delta"], "🩹", "#dc2626", "#fee2e2", invert=True)}
  </div>
</div>

<!-- Daily trends -->
<div class="section">
  <div class="card card-chart">
    <div class="chart-header">
      <span class="chart-title">Daily trends — last 90 days</span>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#4f6ef7"></div>Mood</div>
        <div class="legend-item"><div class="legend-dot" style="background:#0d9488"></div>Energy</div>
        <div class="legend-item"><div class="legend-dot" style="background:#7c3aed"></div>Sleep</div>
        <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Pain</div>
      </div>
    </div>
    <div class="chart-wrap">
      <canvas id="trendsChart"></canvas>
    </div>
  </div>
</div>

<!-- Weight + Labs -->
<div class="section grid grid-2">
  <div class="card card-chart">
    <div class="chart-header">
      <span class="chart-title">Weight timeline</span>
    </div>
    <div class="chart-wrap-sm">
      <canvas id="weightChart"></canvas>
    </div>
  </div>
  <div class="card card-chart">
    <div class="chart-header">
      <span class="chart-title">Lab results vs. reference range</span>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#16a34a"></div>Normal</div>
        <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Out of range</div>
      </div>
    </div>
    <div class="chart-wrap-sm">
      <canvas id="labChart"></canvas>
    </div>
  </div>
</div>

<!-- Medications + Appointments -->
<div class="section grid grid-2">
  <div class="card">
    <div class="section-label" style="margin-bottom:16px">Active medications</div>
    {_medications_html(meds)}
  </div>
  <div class="card">
    <div class="section-label" style="margin-bottom:16px">Upcoming appointments</div>
    {_appointments_html(upcoming_appts)}
  </div>
</div>

<!-- Conditions -->
{_conditions_html(conditions)}

<footer>
  <strong>health-skill</strong>
  <span class="footer-note">⚠️ Not medical advice · For personal awareness only</span>
</footer>

</div><!-- /page -->

<script>
const C = '#6b7280';   // muted tick color
const G = '#f3f4f6';   // grid line color

const BASE = {{
  responsive: true,
  maintainAspectRatio: false,
  interaction: {{ mode: 'index', intersect: false }},
  plugins: {{
    legend: {{ display: false }},
    tooltip: {{
      backgroundColor: '#fff',
      titleColor: '#1a1d2e',
      bodyColor: '#4b5168',
      borderColor: '#e4e7f0',
      borderWidth: 1,
      padding: 10,
      cornerRadius: 8,
    }}
  }},
  scales: {{
    x: {{ ticks: {{ color: C, maxRotation: 0, maxTicksLimit: 8, font: {{ size: 11 }} }}, grid: {{ color: G }} }},
    y: {{ ticks: {{ color: C, font: {{ size: 11 }} }}, grid: {{ color: G }} }}
  }}
}};

// Trends
(function() {{
  const d = {json.dumps(trend_data)};
  if (!d.labels.length) {{ document.getElementById('trendsChart').closest('.card').innerHTML += '<p class="empty" style="margin-top:8px">No check-in data yet.</p>'; return; }}
  new Chart(document.getElementById('trendsChart'), {{
    type: 'line',
    data: {{
      labels: d.labels,
      datasets: [
        {{ label:'Mood',     data:d.mood,   borderColor:'#4f6ef7', backgroundColor:'rgba(79,110,247,.07)', tension:0.4, pointRadius:0, borderWidth:2.5, fill:false }},
        {{ label:'Energy',   data:d.energy, borderColor:'#0d9488', backgroundColor:'rgba(13,148,136,.07)', tension:0.4, pointRadius:0, borderWidth:2.5, fill:false }},
        {{ label:'Sleep (h)',data:d.sleep,  borderColor:'#7c3aed', backgroundColor:'rgba(124,58,237,.05)', tension:0.4, pointRadius:0, borderWidth:2,   fill:false, yAxisID:'y2' }},
        {{ label:'Pain',     data:d.pain,   borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,.05)',  tension:0.4, pointRadius:0, borderWidth:2,   fill:false }},
      ]
    }},
    options: {{
      ...BASE,
      scales: {{
        x:  BASE.scales.x,
        y:  {{ ...BASE.scales.y, min:0, max:10, title:{{ display:true, text:'score /10', color:C, font:{{size:10}} }} }},
        y2: {{ ...BASE.scales.y, position:'right', min:0, max:12, title:{{ display:true, text:'sleep h', color:C, font:{{size:10}} }}, grid:{{ drawOnChartArea:false }} }}
      }}
    }}
  }});
}})();

// Weight
(function() {{
  const d = {json.dumps(weight_data)};
  const el = document.getElementById('weightChart');
  if (!d.labels.length) {{ el.closest('.card').querySelector('.chart-wrap-sm').innerHTML = '<p class="empty">No weight data yet.</p>'; return; }}
  new Chart(el, {{
    type:'line',
    data:{{ labels:d.labels, datasets:[{{
      label:'Weight', data:d.values,
      borderColor:'#d97706', backgroundColor:'rgba(217,119,6,.08)',
      tension:0.3, pointRadius:0, borderWidth:2.5, fill:true
    }}]}},
    options:{{
      ...BASE,
      scales:{{
        x: BASE.scales.x,
        y: {{ ...BASE.scales.y, title:{{ display:true, text:d.unit||'kg', color:C, font:{{size:10}} }} }}
      }}
    }}
  }});
}})();

// Labs
(function() {{
  const d = {json.dumps(lab_chart)};
  const el = document.getElementById('labChart');
  if (!d.labels.length) {{ el.closest('.card').querySelector('.chart-wrap-sm').innerHTML = '<p class="empty">No lab results yet.</p>'; return; }}
  new Chart(el, {{
    type:'bar',
    data:{{ labels:d.labels, datasets:[{{ label:'Value', data:d.values, backgroundColor:d.colors, borderRadius:5, borderSkipped:false }}] }},
    options:{{
      ...BASE,
      indexAxis:'y',
      plugins:{{
        ...BASE.plugins,
        tooltip:{{
          ...BASE.plugins.tooltip,
          callbacks:{{ afterBody: (items) => items.map(i => d.ranges[i.dataIndex]).filter(Boolean) }}
        }}
      }},
      scales:{{
        x: BASE.scales.x,
        y: {{ ...BASE.scales.y, ticks:{{ ...BASE.scales.y.ticks, color:'#1a1d2e', font:{{size:12,weight:'500'}} }} }}
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
            "high": "rgba(220,38,38,0.75)",
            "low": "rgba(220,38,38,0.75)",
            "normal": "rgba(22,163,74,0.7)",
            "optimal": "rgba(79,110,247,0.75)",
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
              icon: str, color: str, bg: str, invert: bool = False) -> str:
    val_str = str(value) if value is not None else "—"
    delta_html = ""
    if delta is not None and delta != 0:
        is_good = (delta > 0) if not invert else (delta < 0)
        cls = "delta-up" if is_good else "delta-down"
        arrow = "↑" if delta > 0 else "↓"
        sign = "+" if delta > 0 else ""
        delta_html = f'<div class="kpi-delta {cls}">{arrow} {sign}{delta} vs prev 30d</div>'
    elif delta == 0:
        delta_html = '<div class="kpi-delta delta-neutral">→ Unchanged</div>'
    return f"""
    <div class="card">
      <div class="kpi-icon" style="background:{bg}">{icon}</div>
      <div class="kpi-value" style="color:{color}">{val_str}<span class="kpi-suffix">{suffix}</span></div>
      <div class="kpi-label">{label}</div>
      {delta_html}
    </div>"""


def _medications_html(meds: list[dict[str, Any]]) -> str:
    active = [m for m in meds if m.get("active", True)]
    if not active:
        return '<p class="empty">No medications recorded.</p>'
    rows = []
    colors = ["#4f6ef7", "#0d9488", "#7c3aed", "#d97706", "#dc2626", "#16a34a"]
    for i, m in enumerate(active):
        name = m.get("name", "Unknown").title()
        dose = m.get("dose", "")
        freq = m.get("frequency", "")
        start = m.get("start_date", "")
        detail = " · ".join(filter(None, [dose, freq]))
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
        dot_color = colors[i % len(colors)]
        rows.append(f"""
        <div class="row">
          <div class="med-dot" style="background:{dot_color}"></div>
          <div style="flex:1;min-width:0">
            <div class="med-name">{name}</div>
            {f'<div class="med-detail">{detail}</div>' if detail else ''}
          </div>
          {f'<div class="med-dur">{dur}</div>' if dur else ''}
        </div>""")
    return "".join(rows)


def _appointments_html(appts: list[dict[str, Any]]) -> str:
    if not appts:
        return '<p class="empty">No upcoming appointments in the next 90 days.</p>'
    rows = []
    today = date.today()
    for a in appts:
        spec = a.get("specialty", "Appointment").title()
        reason = a.get("reason", "")
        d = a.get("date", "")
        try:
            days_until = (date.fromisoformat(d) - today).days
            if days_until == 0:
                badge = '<span class="badge badge-red">Today</span>'
            elif days_until <= 3:
                badge = f'<span class="badge badge-amber">In {days_until}d</span>'
            elif days_until <= 14:
                badge = f'<span class="badge badge-blue">In {days_until}d</span>'
            else:
                badge = f'<span class="badge badge-gray">{d}</span>'
        except ValueError:
            badge = f'<span class="badge badge-gray">{d}</span>'
        rows.append(f"""
        <div class="row">
          {badge}
          <div class="appt-col">
            <div class="appt-name">{spec}</div>
            {f'<div class="appt-reason">{reason}</div>' if reason else ''}
          </div>
        </div>""")
    return "".join(rows)


def _conditions_html(conditions: list[dict[str, Any]]) -> str:
    if not conditions:
        return ""
    chips = []
    for c in conditions:
        name = c.get("name", "")
        since = c.get("diagnosed", "")
        tip = f' title="Diagnosed {since}"' if since else ""
        chips.append(f'<span class="chip"{tip}>🔵 {name}</span>')
    chips_html = "\n".join(chips)
    return f"""
<div class="section">
  <div class="section-label">Conditions</div>
  <div class="card">
    <div class="chips">{chips_html}</div>
  </div>
</div>"""
