#!/usr/bin/env python3
"""HTML artifact generation for Health Skill dashboards.

Generates self-contained single-file HTML with inline CSS and Chart.js charts.
Requires CDN access for Chart.js; renders in any browser or Claude artifact viewer.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# NOTE: keep both import blocks in sync
try:
    from .care_workspace import (
        WorkspaceSnapshot,
        atomic_write_text,
        exports_dir,
        home_path,
        load_snapshot,
        now_utc,
        person_dir,
        staleness_warning,
    )
    from .rendering import (
        build_pattern_insights,
        classify_query_intents,
        current_priorities,
        due_follow_ups,
        latest_recent_tests,
        next_follow_up,
        open_conflicts_only,
        open_reviews,
        pending_follow_ups,
        recent_abnormal_tests,
        suggested_visit_questions,
        thirty_second_summary,
    )
except ImportError:
    from care_workspace import (
        WorkspaceSnapshot,
        atomic_write_text,
        exports_dir,
        home_path,
        load_snapshot,
        now_utc,
        person_dir,
        staleness_warning,
    )
    from rendering import (
        build_pattern_insights,
        classify_query_intents,
        current_priorities,
        due_follow_ups,
        latest_recent_tests,
        next_follow_up,
        open_conflicts_only,
        open_reviews,
        pending_follow_ups,
        recent_abnormal_tests,
        suggested_visit_questions,
        thirty_second_summary,
    )


# ---------------------------------------------------------------------------
# CSS Theme
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg: #0f172a;
    --surface: #1e293b;
    --surface2: #334155;
    --border: #475569;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --accent: #38bdf8;
    --green: #4ade80;
    --yellow: #fbbf24;
    --red: #f87171;
    --orange: #fb923c;
    --purple: #a78bfa;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 24px;
    max-width: 900px;
    margin: 0 auto;
}
h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: 8px; }
h2 { font-size: 1.2rem; font-weight: 600; color: var(--accent); margin: 24px 0 12px; }
h3 { font-size: 1rem; font-weight: 600; margin: 16px 0 8px; }
.subtitle { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 20px; }
.status-bar {
    display: flex; gap: 12px; flex-wrap: wrap;
    padding: 12px 16px; background: var(--surface);
    border-radius: 12px; margin-bottom: 24px;
}
.chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 500;
}
.chip-ok { background: rgba(74,222,128,0.15); color: var(--green); }
.chip-warn { background: rgba(251,191,36,0.15); color: var(--yellow); }
.chip-alert { background: rgba(248,113,113,0.15); color: var(--red); }
.card {
    background: var(--surface); border-radius: 12px;
    padding: 16px 20px; margin-bottom: 16px;
    border: 1px solid var(--border);
}
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-title { font-weight: 600; }
.card-badge {
    font-size: 0.75rem; padding: 2px 8px; border-radius: 10px;
    background: var(--surface2); color: var(--text-muted);
}
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric-card {
    background: var(--surface); border-radius: 10px; padding: 14px 16px;
    border: 1px solid var(--border); text-align: center;
}
.metric-value { font-size: 1.6rem; font-weight: 700; }
.metric-label { font-size: 0.8rem; color: var(--text-muted); margin-top: 2px; }
.metric-delta { font-size: 0.85rem; margin-top: 4px; }
.delta-good { color: var(--green); }
.delta-bad { color: var(--red); }
.delta-neutral { color: var(--text-muted); }
ul { list-style: none; padding: 0; }
li { padding: 6px 0; border-bottom: 1px solid var(--surface2); display: flex; align-items: center; gap: 8px; }
li:last-child { border-bottom: none; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-green { background: var(--green); }
.dot-yellow { background: var(--yellow); }
.dot-red { background: var(--red); }
.dot-gray { background: var(--text-muted); }
.flag-high { color: var(--red); font-weight: 600; }
.flag-low { color: var(--orange); font-weight: 600; }
.flag-normal { color: var(--green); }
svg { display: block; margin: 8px 0; }
.chart-container { padding: 8px 0; }
.stale-banner {
    background: rgba(251,191,36,0.1); border: 1px solid var(--yellow);
    border-radius: 8px; padding: 10px 16px; margin-bottom: 16px;
    color: var(--yellow); font-size: 0.9rem;
}
.section-divider { border: none; border-top: 1px solid var(--surface2); margin: 20px 0; }
.tag {
    display: inline-block; font-size: 0.75rem; padding: 2px 8px;
    border-radius: 6px; margin-right: 4px;
}
.tag-active { background: rgba(74,222,128,0.15); color: var(--green); }
.tag-pending { background: rgba(251,191,36,0.15); color: var(--yellow); }
.tag-alert { background: rgba(248,113,113,0.15); color: var(--red); }
footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--surface2); color: var(--text-muted); font-size: 0.8rem; }
"""


# ---------------------------------------------------------------------------
# Chart.js Helpers
# ---------------------------------------------------------------------------

def _chart_line(
    charts: list[tuple[str, dict]],
    labels: list[str],
    datasets: list[dict],
    ref_low: float | None = None,
    ref_high: float | None = None,
    y_label: str = "",
) -> str:
    """Return canvas HTML for a Chart.js line chart; append config to *charts*."""
    chart_id = f"chart-{len(charts)}"
    ds = []
    for d in datasets:
        ds.append({
            "label": d.get("label", ""),
            "data": d.get("data", []),
            "borderColor": d.get("borderColor", "#38bdf8"),
            "backgroundColor": d.get("backgroundColor", "rgba(56,189,248,0.1)"),
            "borderWidth": d.get("borderWidth", 2.5),
            "pointRadius": d.get("pointRadius", 5),
            "pointBackgroundColor": d.get("pointBackgroundColor", d.get("borderColor", "#38bdf8")),
            "tension": d.get("tension", 0.3),
            "fill": d.get("fill", True),
        })
        # Copy optional keys
        for key in ("borderDash", "pointRadius", "order"):
            if key in d:
                ds[-1][key] = d[key]
    # Reference range as a filled band
    if ref_high is not None:
        ref_data = [ref_high] * len(labels)
        ds.append({
            "label": "Reference Range",
            "data": ref_data,
            "borderColor": "rgba(74,222,128,0.3)",
            "backgroundColor": "rgba(74,222,128,0.05)",
            "borderWidth": 1,
            "borderDash": [5, 5],
            "pointRadius": 0,
            "fill": True,
            "tension": 0,
        })
    config: dict[str, Any] = {
        "type": "line",
        "data": {"labels": labels, "datasets": ds},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "legend": {"display": True, "labels": {"color": "#e2e8f0"}},
                "tooltip": {"enabled": True},
            },
            "scales": {
                "x": {"ticks": {"color": "#94a3b8"}, "grid": {"color": "#334155"}},
                "y": {"ticks": {"color": "#94a3b8"}, "grid": {"color": "#334155"}},
            },
        },
    }
    charts.append((chart_id, config))
    return f'<div style="height:220px"><canvas id="{chart_id}"></canvas></div>'


# ---------------------------------------------------------------------------
# HTML Section Builders
# ---------------------------------------------------------------------------

def _esc(text: Any) -> str:
    return html.escape(str(text)) if text else ""


def _chip(ok: bool, good: str, bad: str) -> str:
    cls = "chip-ok" if ok else "chip-warn"
    icon = "✓" if ok else "!"
    text = good if ok else bad
    return f'<span class="chip {cls}">{icon} {_esc(text)}</span>'


def _flag_class(flag: str) -> str:
    if flag in ("high", "abnormal"):
        return "flag-high"
    if flag == "low":
        return "flag-low"
    return "flag-normal"


def _dot_class(flag: str) -> str:
    if flag in ("high", "abnormal"):
        return "dot-red"
    if flag == "low":
        return "dot-yellow"
    if flag == "normal":
        return "dot-green"
    return "dot-gray"


def _parse_ref_range(ref: str) -> tuple[float | None, float | None]:
    """Parse '0-99 mg/dL' into (0.0, 99.0)."""
    import re
    m = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", ref)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def build_health_home_html(snap: WorkspaceSnapshot) -> str:
    """Generate the main Health Home artifact."""
    p = snap.profile
    name = p.get("name") or "Unknown"
    stale = staleness_warning(p)

    # Status chips
    inbox_ok = len(snap.inbox_files) == 0
    reviews_ok = len(snap.open_review_items) == 0
    conflicts_ok = len(snap.open_conflicts) == 0
    overdue = due_follow_ups(p, days=0)
    overdue_ok = len(overdue) == 0

    # Priorities
    priorities = current_priorities(p, snap.conflicts, snap.inbox_files, snap.review_queue)

    # Pattern insights
    insights = build_pattern_insights(p, snap.medication_history, snap.weight_entries, snap.vital_entries)

    # Lab trend charts
    from collections import defaultdict
    grouped_tests: dict[str, list[dict]] = defaultdict(list)
    for t in p.get("recent_tests", []):
        try:
            float(t.get("value", ""))
            grouped_tests[t.get("name", "unknown")].append(t)
        except (ValueError, TypeError):
            pass

    # Weight chart
    weight_points = [(e["entry_date"][5:], e["value"]) for e in snap.weight_entries]

    # BP chart
    bp_entries = [e for e in snap.vital_entries if e.get("metric") == "blood_pressure"]
    bp_systolic = []
    bp_diastolic = []
    for e in bp_entries:
        s, d = e.get("systolic"), e.get("diastolic")
        if s and d:
            bp_systolic.append((e["entry_date"][5:], float(s)))
            bp_diastolic.append((e["entry_date"][5:], float(d)))

    # Next follow-up
    nf = next_follow_up(p)

    # Build HTML
    charts: list[tuple[str, dict]] = []
    sections = []

    # Header
    sections.append(f"<h1>{_esc(name)}</h1>")
    sections.append(f'<div class="subtitle">Health Home &middot; {date.today().isoformat()}</div>')

    # Staleness banner
    if stale:
        sections.append(f'<div class="stale-banner">⚠ {_esc(stale)}</div>')

    # Status bar
    sections.append('<div class="status-bar">')
    sections.append(_chip(inbox_ok, "Inbox clear", f"{len(snap.inbox_files)} file(s) in inbox"))
    sections.append(_chip(reviews_ok, "No items need review", f"{len(snap.open_review_items)} item(s) need review"))
    sections.append(_chip(conflicts_ok, "No conflicts", f"{len(snap.open_conflicts)} conflict(s) open"))
    sections.append(_chip(overdue_ok, "No overdue follow-ups", f"{len(overdue)} overdue"))
    sections.append("</div>")

    # Metric cards
    sections.append('<div class="grid">')
    # Conditions count
    sections.append(f"""<div class="metric-card">
        <div class="metric-value">{len(p.get('conditions', []))}</div>
        <div class="metric-label">Active Conditions</div>
    </div>""")
    # Medications
    sections.append(f"""<div class="metric-card">
        <div class="metric-value">{len(p.get('medications', []))}</div>
        <div class="metric-label">Medications</div>
    </div>""")
    # Weight
    if snap.weight_entries:
        latest_w = snap.weight_entries[-1]
        delta = ""
        if len(snap.weight_entries) >= 2:
            change = latest_w["value"] - snap.weight_entries[0]["value"]
            pct = (change / snap.weight_entries[0]["value"]) * 100
            cls = "delta-good" if change <= 0 else "delta-bad"
            delta = f'<div class="metric-delta {cls}">{change:+.1f} kg ({pct:+.1f}%)</div>'
        sections.append(f"""<div class="metric-card">
            <div class="metric-value">{latest_w['value']:.1f}</div>
            <div class="metric-label">Weight (kg)</div>
            {delta}
        </div>""")
    # Follow-ups
    sections.append(f"""<div class="metric-card">
        <div class="metric-value">{len(pending_follow_ups(p))}</div>
        <div class="metric-label">Pending Follow-ups</div>
    </div>""")
    sections.append("</div>")

    # Priorities
    if priorities:
        sections.append("<h2>Right Now</h2>")
        sections.append('<div class="card"><ul>')
        for item in priorities:
            sections.append(f"<li><span class='dot dot-yellow'></span>{_esc(item)}</li>")
        sections.append("</ul></div>")

    # Next follow-up
    if nf:
        sections.append("<h2>Next Follow-Up</h2>")
        sections.append(f'<div class="card">')
        sections.append(f"<strong>{_esc(nf.get('task', ''))}</strong><br>")
        sections.append(f'<span class="tag tag-pending">due {_esc(nf.get("due_date", "unknown"))}</span>')
        sections.append("</div>")

    # Lab trends
    for test_name in sorted(grouped_tests):
        series = sorted(grouped_tests[test_name], key=lambda t: t.get("date", ""))
        if len(series) < 2:
            continue
        points = [(t.get("date", "?")[5:], float(t.get("value", 0))) for t in series]
        ref = series[-1].get("reference_range", "")
        ref_low, ref_high = _parse_ref_range(ref)
        flag = series[-1].get("flag", "")
        color = "#f87171" if flag in ("high", "abnormal") else "#fbbf24" if flag == "low" else "#4ade80"

        sections.append(f"<h2>{_esc(test_name)}</h2>")
        sections.append('<div class="card">')
        latest = series[-1]
        sections.append(f'<div class="card-header"><span class="card-title">{_esc(latest.get("value"))} {_esc(latest.get("unit", ""))}</span>')
        if flag:
            sections.append(f'<span class="{_flag_class(flag)}">{_esc(flag)}</span>')
        sections.append("</div>")
        if ref:
            sections.append(f'<div style="color:var(--text-muted);font-size:0.85rem">Reference: {_esc(ref)}</div>')
        sections.append('<div class="chart-container">')
        chart_labels = [lbl for lbl, _ in points]
        chart_data = [v for _, v in points]
        sections.append(_chart_line(charts, labels=chart_labels, datasets=[{
            "label": test_name, "data": chart_data,
            "borderColor": color, "backgroundColor": color.replace(")", ",0.1)").replace("rgb", "rgba") if "rgba" not in color else color,
            "pointBackgroundColor": color,
        }], ref_low=ref_low, ref_high=ref_high))
        sections.append("</div></div>")

    # Weight trend
    if len(weight_points) >= 2:
        sections.append("<h2>Weight</h2>")
        sections.append('<div class="card"><div class="chart-container">')
        sections.append(_chart_line(charts, labels=[lbl for lbl, _ in weight_points], datasets=[{
            "label": "Weight", "data": [v for _, v in weight_points],
            "borderColor": "#a78bfa", "backgroundColor": "rgba(167,139,250,0.1)",
            "pointBackgroundColor": "#a78bfa",
        }]))
        sections.append("</div></div>")

    # Blood pressure
    if len(bp_systolic) >= 2:
        sections.append("<h2>Blood Pressure</h2>")
        sections.append('<div class="card"><div class="chart-container">')
        sections.append(_chart_line(charts, labels=[lbl for lbl, _ in bp_systolic], datasets=[{
            "label": "Systolic", "data": [v for _, v in bp_systolic],
            "borderColor": "#fb923c", "backgroundColor": "rgba(251,146,60,0.1)",
            "pointBackgroundColor": "#fb923c",
        }]))
        sections.append("</div></div>")

    # Abnormal labs
    abnormal = recent_abnormal_tests(p, limit=5)
    if abnormal:
        sections.append("<h2>Abnormal Results</h2>")
        sections.append('<div class="card"><ul>')
        for t in abnormal:
            sections.append(f"""<li>
                <span class="dot {_dot_class(t.get('flag',''))}" ></span>
                <strong>{_esc(t.get('name'))}</strong> {_esc(t.get('value'))} {_esc(t.get('unit',''))}
                <span class="{_flag_class(t.get('flag',''))}">{_esc(t.get('flag',''))}</span>
                <span style="color:var(--text-muted);margin-left:auto;font-size:0.85rem">{_esc(t.get('date',''))}</span>
            </li>""")
        sections.append("</ul></div>")

    # Medications
    meds = p.get("medications", [])
    if meds:
        sections.append("<h2>Medications</h2>")
        sections.append('<div class="card"><ul>')
        for m in meds:
            status = m.get("status", "")
            tag_cls = "tag-active" if status == "active" else "tag-pending"
            sections.append(f"""<li>
                <strong>{_esc(m.get('name'))}</strong> {_esc(m.get('dose',''))} {_esc(m.get('frequency',''))}
                <span class="tag {tag_cls}">{_esc(status)}</span>
            </li>""")
        sections.append("</ul></div>")

    # Allergies
    allergies = p.get("allergies", [])
    if allergies:
        sections.append("<h2>Allergies</h2>")
        sections.append('<div class="card"><ul>')
        for a in allergies:
            severity = a.get("severity_level") or a.get("severity", "")
            dot = "dot-red" if severity in ("severe", "life-threatening") else "dot-yellow"
            sections.append(f"""<li>
                <span class="dot {dot}"></span>
                <strong>{_esc(a.get('substance'))}</strong> — {_esc(a.get('reaction',''))}
                <span class="tag tag-alert">{_esc(severity)}</span>
            </li>""")
        sections.append("</ul></div>")

    # Patterns
    if insights:
        sections.append("<h2>Connected Patterns</h2>")
        sections.append('<div class="card"><ul>')
        for insight in insights:
            sections.append(f"<li><span class='dot dot-yellow'></span>{_esc(insight)}</li>")
        sections.append("</ul></div>")

    # Questions
    questions = suggested_visit_questions(p)
    if questions:
        sections.append("<h2>Questions To Ask</h2>")
        sections.append('<div class="card"><ul>')
        for q in questions[:4]:
            sections.append(f"<li>{_esc(q)}</li>")
        sections.append("</ul></div>")

    # Footer
    sections.append(f'<footer>Generated {date.today().isoformat()} &middot; Health Skill &middot; Not medical advice</footer>')

    body = "\n".join(sections)
    return _wrap_html(f"{name} — Health Home", body, charts=charts)


def build_query_dashboard_html(
    query: str,
    snap: WorkspaceSnapshot,
) -> str:
    """Generate a query-focused HTML dashboard artifact."""
    from collections import defaultdict

    p = snap.profile
    intents = classify_query_intents(query, max_intents=2)
    title = f"Dashboard: {query}"

    charts: list[tuple[str, dict]] = []
    sections = []
    sections.append(f'<h1>{_esc(query)}</h1>')
    sections.append(f'<div class="subtitle">Intent: {", ".join(intents)} &middot; {date.today().isoformat()}</div>')

    stale = staleness_warning(p)
    if stale:
        sections.append(f'<div class="stale-banner">⚠ {_esc(stale)}</div>')

    # Summary
    sections.append('<div class="card">')
    sections.append(f"<strong>{_esc(p.get('name', 'Unknown'))}</strong><br>")
    sections.append(f'{_esc(thirty_second_summary(p, snap.conflicts, snap.review_queue))}')
    sections.append("</div>")

    # Relevant labs with charts
    grouped: dict[str, list[dict]] = defaultdict(list)
    for t in p.get("recent_tests", []):
        try:
            float(t.get("value", ""))
            grouped[t.get("name", "")].append(t)
        except (ValueError, TypeError):
            pass

    if any(i in intents for i in ("lab_review", "visit_prep", "caregiver_overview")):
        for name in sorted(grouped):
            series = sorted(grouped[name], key=lambda t: t.get("date", ""))
            points = [(t.get("date", "?")[5:], float(t.get("value", 0))) for t in series]
            ref = series[-1].get("reference_range", "")
            ref_low, ref_high = _parse_ref_range(ref)
            flag = series[-1].get("flag", "")
            color = "#f87171" if flag in ("high", "abnormal") else "#fbbf24" if flag == "low" else "#4ade80"

            sections.append(f"<h2>{_esc(name)}</h2>")
            sections.append('<div class="card">')
            sections.append(f'<strong>{_esc(series[-1].get("value"))} {_esc(series[-1].get("unit",""))}</strong>')
            if flag:
                sections.append(f' <span class="{_flag_class(flag)}">{_esc(flag)}</span>')
            if len(points) >= 2:
                sections.append('<div class="chart-container">')
                chart_labels = [lbl for lbl, _ in points]
                chart_data = [v for _, v in points]
                sections.append(_chart_line(charts, labels=chart_labels, datasets=[{
                    "label": name, "data": chart_data,
                    "borderColor": color, "backgroundColor": color.replace(")", ",0.1)").replace("rgb", "rgba") if "rgba" not in color else color,
                    "pointBackgroundColor": color,
                }], ref_low=ref_low, ref_high=ref_high))
                sections.append("</div>")
            sections.append("</div>")

    # Medications
    if any(i in intents for i in ("medication_review", "visit_prep", "symptom_triage", "caregiver_overview", "medication_reconciliation", "side_effect_check")):
        meds = p.get("medications", [])
        if meds:
            sections.append("<h2>Medications</h2>")
            sections.append('<div class="card"><ul>')
            for m in meds:
                sections.append(f"<li><strong>{_esc(m.get('name'))}</strong> {_esc(m.get('dose',''))} {_esc(m.get('frequency',''))}</li>")
            sections.append("</ul></div>")

    # Vitals
    if any(i in intents for i in ("weight_vitals", "visit_prep", "symptom_triage", "caregiver_overview")):
        bp = [e for e in snap.vital_entries if e.get("metric") == "blood_pressure"]
        bp_points = [(e["entry_date"][5:], float(e.get("systolic", 0))) for e in bp if e.get("systolic")]
        if len(bp_points) >= 2:
            sections.append("<h2>Blood Pressure</h2>")
            sections.append('<div class="card"><div class="chart-container">')
            sections.append(_chart_line(charts, labels=[lbl for lbl, _ in bp_points], datasets=[{
                "label": "Systolic", "data": [v for _, v in bp_points],
                "borderColor": "#fb923c", "backgroundColor": "rgba(251,146,60,0.1)",
                "pointBackgroundColor": "#fb923c",
            }]))
            sections.append("</div></div>")

        if len(snap.weight_entries) >= 2:
            wp = [(e["entry_date"][5:], e["value"]) for e in snap.weight_entries]
            sections.append("<h2>Weight</h2>")
            sections.append('<div class="card"><div class="chart-container">')
            sections.append(_chart_line(charts, labels=[lbl for lbl, _ in wp], datasets=[{
                "label": "Weight", "data": [v for _, v in wp],
                "borderColor": "#a78bfa", "backgroundColor": "rgba(167,139,250,0.1)",
                "pointBackgroundColor": "#a78bfa",
            }]))
            sections.append("</div></div>")

    # Patterns
    insights = build_pattern_insights(p, snap.medication_history, snap.weight_entries, snap.vital_entries)
    if insights:
        sections.append("<h2>Patterns</h2>")
        sections.append('<div class="card"><ul>')
        for ins in insights:
            sections.append(f"<li><span class='dot dot-yellow'></span>{_esc(ins)}</li>")
        sections.append("</ul></div>")

    # Follow-ups
    if any(i in intents for i in ("follow_up", "visit_prep", "caregiver_overview")):
        pending = pending_follow_ups(p)
        if pending:
            sections.append("<h2>Follow-Ups</h2>")
            sections.append('<div class="card"><ul>')
            for f in pending[:5]:
                sections.append(f'<li><span class="dot dot-yellow"></span><strong>{_esc(f.get("task",""))}</strong> — {_esc(f.get("due_date",""))}</li>')
            sections.append("</ul></div>")

    # Questions
    questions = suggested_visit_questions(p)
    if questions:
        sections.append("<h2>Questions</h2>")
        sections.append('<div class="card"><ul>')
        for q in questions[:4]:
            sections.append(f"<li>{_esc(q)}</li>")
        sections.append("</ul></div>")

    sections.append(f'<footer>Generated {date.today().isoformat()} &middot; Health Skill &middot; Not medical advice</footer>')

    return _wrap_html(title, "\n".join(sections), charts=charts)


def _wrap_html(title: str, body: str, charts: list[tuple[str, dict]] | None = None) -> str:
    chart_script = ""
    if charts:
        charts_dict = {cid: cfg for cid, cfg in charts}
        chart_script = (
            '\n<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>\n'
            "<script>\n"
            f"const charts = {json.dumps(charts_dict)};\n"
            "Chart.defaults.color = '#94a3b8';\n"
            "Chart.defaults.borderColor = '#334155';\n"
            "for (const [id, config] of Object.entries(charts)) {\n"
            "  const ctx = document.getElementById(id);\n"
            "  if (ctx) new Chart(ctx, config);\n"
            "}\n"
            "</script>\n"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
{body}
{chart_script}</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_health_home_artifact(root: Path, person_id: str) -> Path:
    """Generate HEALTH_HOME.html from workspace data."""
    snap = load_snapshot(root, person_id)
    html_text = build_health_home_html(snap)
    output = person_dir(root, person_id) / "HEALTH_HOME.html"
    atomic_write_text(output, html_text)
    return output


def generate_query_dashboard_artifact(root: Path, person_id: str, query: str) -> Path:
    """Generate QUERY_DASHBOARD.html from workspace data and query."""
    snap = load_snapshot(root, person_id)
    html_text = build_query_dashboard_html(query, snap)
    output = exports_dir(root, person_id) / "QUERY_DASHBOARD.html"
    atomic_write_text(output, html_text)
    return output


# ---------------------------------------------------------------------------
# Longevity Dashboard (v1.7)
# ---------------------------------------------------------------------------

def _empty_card(title: str, cta: str) -> str:
    return (
        f'<div class="card"><div class="card-header"><span class="card-title">{_esc(title)}</span></div>'
        f'<div style="color:var(--text-muted);font-size:0.9rem">No data yet. {_esc(cta)}</div></div>'
    )


def build_longevity_dashboard_html(root: Path, person_id: str) -> str:
    """Build a comprehensive longevity dashboard HTML."""
    # Local imports to avoid circular deps at module load
    try:
        from .care_workspace import calculate_age_from_dob, load_snapshot
        from .preventive import compute_due_screenings
        from .connections import build_connections
    except ImportError:
        from care_workspace import calculate_age_from_dob, load_snapshot  # type: ignore
        from preventive import compute_due_screenings  # type: ignore
        from connections import build_connections  # type: ignore

    snap = load_snapshot(root, person_id)
    p = snap.profile
    charts: list[tuple[str, dict]] = []
    sections: list[str] = []

    name = p.get("name") or "Your"
    age = calculate_age_from_dob(p.get("date_of_birth", ""))

    sections.append(f'<h1>{_esc(name)} — Longevity Dashboard</h1>')
    sections.append(f'<div class="subtitle">Generated {date.today().isoformat()}</div>')

    stale = staleness_warning(p)
    if stale:
        sections.append(f'<div class="stale-banner">{_esc(stale)}</div>')

    # --- Top status bar ---
    weights = snap.weight_entries
    vitals = snap.vital_entries
    latest_weight = weights[-1] if weights else None
    # crude BMI (needs height in prefs.height_cm)
    bmi = None
    height_cm = p.get("preferences", {}).get("height_cm")
    if latest_weight and height_cm:
        try:
            h_m = float(height_cm) / 100.0
            w_kg = float(latest_weight["value"])
            if latest_weight.get("unit") == "lb":
                w_kg = w_kg * 0.4536
            if h_m > 0:
                bmi = w_kg / (h_m * h_m)
        except (TypeError, ValueError):
            bmi = None

    rhr_vals = [v["numeric_value"] for v in vitals if v.get("metric") == "heart_rate" and v.get("numeric_value") is not None]
    rhr = round(rhr_vals[-1]) if rhr_vals else None

    bp_vals = [v for v in vitals if v.get("metric") == "blood_pressure" and v.get("systolic") and v.get("diastolic")]
    bp_cat = ""
    if bp_vals:
        last = bp_vals[-1]
        s, d = int(last["systolic"]), int(last["diastolic"])
        if s < 120 and d < 80:
            bp_cat = "Normal"
        elif s < 130 and d < 80:
            bp_cat = "Elevated"
        elif s < 140 or d < 90:
            bp_cat = "Stage 1"
        else:
            bp_cat = "Stage 2"

    last_lab_date = ""
    for t in p.get("recent_tests", []):
        d = t.get("date", "")
        if d > last_lab_date:
            last_lab_date = d

    screenings = compute_due_screenings(p)
    overdue_count = sum(1 for s in screenings if s["status"] == "overdue")

    chips = []
    chips.append(f'<span class="chip chip-ok">Age {age}</span>')
    if bmi:
        chips.append(f'<span class="chip chip-ok">BMI {bmi:.1f}</span>')
    if rhr:
        chips.append(f'<span class="chip chip-ok">RHR {rhr}</span>')
    if bp_cat:
        cls = "chip-ok" if bp_cat == "Normal" else "chip-warn" if bp_cat == "Elevated" else "chip-alert"
        chips.append(f'<span class="chip {cls}">BP {_esc(bp_cat)}</span>')
    if last_lab_date:
        chips.append(f'<span class="chip chip-ok">Last lab {_esc(last_lab_date)}</span>')
    chips.append(f'<span class="chip {"chip-alert" if overdue_count else "chip-ok"}">Overdue screenings: {overdue_count}</span>')
    sections.append('<div class="status-bar">' + "".join(chips) + "</div>")

    # --- Check-in trends (last 30 days) ---
    sections.append("<h2>Daily Check-in Trends (last 30 days)</h2>")
    checkins = p.get("daily_checkins", [])
    cutoff_dt = date.today() - timedelta(days=30)
    ci_recent = []
    for c in checkins:
        try:
            d = datetime.strptime(str(c.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= cutoff_dt:
            ci_recent.append((d, c))
    ci_recent.sort(key=lambda x: x[0])
    if ci_recent:
        labels = [d.isoformat()[5:] for d, _ in ci_recent]
        def _num(c, key):
            v = c.get(key)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
        mood = [_num(c, "mood") for _, c in ci_recent]
        sleep = [_num(c, "sleep") or _num(c, "sleep_hours") for _, c in ci_recent]
        energy = [_num(c, "energy") for _, c in ci_recent]
        pain = [_num(c, "pain") for _, c in ci_recent]
        sections.append('<div class="card"><div class="chart-container">')
        sections.append(_chart_line(charts, labels=labels, datasets=[
            {"label": "Mood", "data": mood, "borderColor": "#38bdf8", "fill": False},
            {"label": "Sleep (h)", "data": sleep, "borderColor": "#a78bfa", "fill": False},
            {"label": "Energy", "data": energy, "borderColor": "#4ade80", "fill": False},
            {"label": "Pain", "data": pain, "borderColor": "#f87171", "fill": False},
        ]))
        sections.append("</div></div>")
    else:
        sections.append(_empty_card("Check-ins", "Try: 'slept 7h, mood 8, energy 7'"))

    # --- Training volume last 12 weeks ---
    sections.append("<h2>Training Volume (weekly, last 12 weeks)</h2>")
    workouts = p.get("workouts", [])
    weeks_ago_12 = date.today() - timedelta(weeks=12)
    wk_buckets: dict[str, int] = {}
    for w in workouts:
        try:
            d = datetime.strptime(str(w.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < weeks_ago_12:
            continue
        # ISO week label
        iso = d.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        mins = 0
        try:
            mins = int(float(w.get("duration_minutes") or w.get("duration") or 0))
        except (TypeError, ValueError):
            mins = 0
        if not mins:
            mins = 30  # default estimate
        wk_buckets[key] = wk_buckets.get(key, 0) + mins
    if wk_buckets:
        ordered = sorted(wk_buckets.items())
        sections.append('<div class="card"><div class="chart-container">')
        sections.append(_chart_line(charts, labels=[k for k, _ in ordered], datasets=[{
            "label": "Minutes/week", "data": [v for _, v in ordered],
            "borderColor": "#4ade80", "backgroundColor": "rgba(74,222,128,0.15)",
        }]))
        sections.append("</div></div>")
    else:
        sections.append(_empty_card("Training", "Log a workout: 'ran 5k in 28 min'"))

    # --- Cycle overview ---
    sections.append("<h2>Cycle Overview</h2>")
    cycles = p.get("cycles", [])
    if cycles:
        last6 = cycles[-6:]
        lengths = []
        prev = None
        for c in last6:
            try:
                s = datetime.strptime(str(c.get("start_date", ""))[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if prev:
                lengths.append((s - prev).days)
            prev = s
        avg = f"{statistics_mean(lengths):.1f}" if lengths else "-"
        rows = "".join(
            f"<li><strong>{_esc(c.get('start_date',''))}</strong> — flow: {_esc(c.get('flow',''))} — {_esc(', '.join(c.get('symptoms', []) if isinstance(c.get('symptoms'), list) else [str(c.get('symptoms',''))])) if c.get('symptoms') else ''}</li>"
            for c in last6
        )
        sections.append(f'<div class="card"><div>Avg cycle length: {avg} days</div><ul>{rows}</ul></div>')
    else:
        sections.append(_empty_card("Cycle tracking", "Opt in with preferences.track_cycles=true, then log a period."))

    # --- Preventive care ---
    sections.append("<h2>Preventive Care</h2>")
    if screenings:
        icon = {"overdue": "⚠", "due_soon": "!", "up_to_date": "✓", "not_yet": "·", "not_applicable": "—"}
        dot = {"overdue": "dot-red", "due_soon": "dot-yellow", "up_to_date": "dot-green", "not_yet": "dot-gray", "not_applicable": "dot-gray"}
        items = sorted(screenings, key=lambda r: ["overdue", "due_soon", "up_to_date", "not_yet", "not_applicable"].index(r["status"]))
        sections.append('<div class="card"><ul>')
        for r in items:
            pretty = r["name"].replace("_", " ").title()
            sections.append(
                f'<li><span class="dot {dot[r["status"]]}"></span>{icon[r["status"]]} <strong>{_esc(pretty)}</strong>'
                f' <span style="color:var(--text-muted);margin-left:auto;font-size:0.85rem">{_esc(r.get("reason",""))}</span></li>'
            )
        sections.append("</ul></div>")
    else:
        sections.append(_empty_card("Preventive care", "Add date of birth and sex to your profile."))

    # --- Cross-domain insights ---
    sections.append("<h2>Cross-Domain Insights</h2>")
    try:
        insights = build_connections(root, person_id)
    except Exception:
        insights = []
    if insights:
        sections.append('<div class="card"><ul>')
        for i in insights:
            conf_cls = {"high": "tag-active", "medium": "tag-pending", "low": "tag-alert"}.get(i["confidence"], "tag-pending")
            sections.append(
                f'<li><strong>{_esc(i["title"])}</strong> <span class="tag {conf_cls}">{_esc(i["confidence"])}</span><br>'
                f'<span style="color:var(--text-muted);font-size:0.9rem">{_esc(i["detail"])}</span></li>'
            )
        sections.append("</ul></div>")
    else:
        sections.append(_empty_card("Insights", "Log 2+ weeks of check-ins and workouts to surface patterns."))

    # --- Labs vs goals ---
    sections.append("<h2>Key Labs</h2>")
    key_labs = [t for t in p.get("recent_tests", []) if str(t.get("name", "")).upper() in {"LDL", "HDL", "A1C", "TSH", "TOTAL CHOLESTEROL"}]
    if key_labs:
        sections.append('<div class="card"><ul>')
        for t in key_labs[-8:]:
            flag = t.get("flag", "")
            sections.append(
                f'<li><span class="dot {_dot_class(flag)}"></span>'
                f'<strong>{_esc(t.get("name"))}</strong> {_esc(t.get("value"))} {_esc(t.get("unit",""))} '
                f'<span class="{_flag_class(flag)}">{_esc(flag)}</span>'
                f'<span style="color:var(--text-muted);margin-left:auto;font-size:0.85rem">{_esc(t.get("date",""))}</span></li>'
            )
        sections.append("</ul></div>")
    else:
        sections.append(_empty_card("Labs", "Drop a lab report into inbox/ to extract."))

    sections.append(f'<footer>Generated {date.today().isoformat()} · Health Skill · Not medical advice</footer>')
    return _wrap_html(f"{name} — Longevity Dashboard", "\n".join(sections), charts=charts)


def statistics_mean(values: list[float]) -> float:
    """Tiny local mean to avoid top-level statistics import change."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def generate_longevity_dashboard_artifact(root: Path, person_id: str) -> Path:
    """Generate LONGEVITY.html — the comprehensive longevity dashboard."""
    try:
        from .care_workspace import longevity_dashboard_path
    except ImportError:
        from care_workspace import longevity_dashboard_path  # type: ignore
    html_text = build_longevity_dashboard_html(root, person_id)
    output = longevity_dashboard_path(root, person_id)
    atomic_write_text(output, html_text)
    return output
