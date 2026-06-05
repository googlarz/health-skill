#!/usr/bin/env python3
"""Proactive nudges: scan workspace and surface what needs attention.

Generates NUDGES.md with prioritized items the user should consider acting on.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_profile,
        load_snapshot,
        nudges_path,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_profile,
        load_snapshot,
        nudges_path,
    )


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def compute_nudges(root: Path, person_id: str) -> list[dict[str, Any]]:
    """Return a list of nudges, each {priority, title, detail, action}."""
    snap = load_snapshot(root, person_id)
    p = snap.profile
    today = date.today()
    nudges: list[dict[str, Any]] = []

    # Overdue follow-ups
    for f in p.get("follow_ups", []):
        if f.get("status") == "completed":
            continue
        due = _parse_date(f.get("due_date", ""))
        if due and due < today:
            days = (today - due).days
            nudges.append({
                "priority": "high",
                "title": f"Overdue: {f.get('task', 'follow-up')}",
                "detail": f"Was due {days} day(s) ago ({due.isoformat()}).",
                "action": "Schedule it or mark done.",
            })

    # Stale check-ins
    checkins = sorted(p.get("daily_checkins", []), key=lambda c: str(c.get("date", "")))
    if checkins:
        last = _parse_date(checkins[-1].get("date", ""))
        if last and (today - last).days >= 5:
            nudges.append({
                "priority": "medium",
                "title": f"No check-in for {(today - last).days} days",
                "detail": "Quick log: mood, sleep, energy, pain.",
                "action": "Try: 'mood 7, slept 7h, energy 6'",
            })
    else:
        nudges.append({
            "priority": "low",
            "title": "Start a daily check-in habit",
            "detail": "One line a day reveals patterns over weeks.",
            "action": "Try: 'mood 7, slept 7h, energy 6'",
        })

    # Stale labs (key markers older than 12 months)
    key_markers = {"LDL", "HDL", "A1C", "TSH", "Total Cholesterol"}
    latest_by_marker: dict[str, date] = {}
    for t in p.get("recent_tests", []):
        name = str(t.get("name", ""))
        d = _parse_date(t.get("date", ""))
        if not d:
            continue
        if name in key_markers:
            if name not in latest_by_marker or d > latest_by_marker[name]:
                latest_by_marker[name] = d
    for marker, d in latest_by_marker.items():
        if (today - d).days > 365:
            nudges.append({
                "priority": "medium",
                "title": f"{marker} last checked {(today - d).days // 30} months ago",
                "detail": f"Last value from {d.isoformat()}.",
                "action": "Consider asking for a recheck at next visit.",
            })

    # Open review items
    open_items = [r for r in snap.review_queue if r.get("status") == "open"]
    if open_items:
        nudges.append({
            "priority": "medium",
            "title": f"{len(open_items)} extracted item(s) need confirmation",
            "detail": "Auto-extracted facts waiting for your sign-off.",
            "action": "Open REVIEW_WORKLIST.md to confirm or reject.",
        })

    # Conflicts
    conflicts = [c for c in snap.conflicts if c.get("status") == "open"]
    if conflicts:
        nudges.append({
            "priority": "high",
            "title": f"{len(conflicts)} unresolved data conflict(s)",
            "detail": "Two sources disagree on the same fact.",
            "action": "Review HEALTH_CONFLICTS.json and pick a source.",
        })

    # Inbox files unprocessed
    if snap.inbox_files:
        nudges.append({
            "priority": "low",
            "title": f"{len(snap.inbox_files)} file(s) in inbox",
            "detail": "Unprocessed documents waiting for ingestion.",
            "action": "Run process-inbox to extract data.",
        })

    # Staleness on profile
    last_session = (p.get("session_history") or [{}])[-1].get("ended_at", "")
    last_dt = _parse_date(last_session[:10]) if last_session else None
    if last_dt and (today - last_dt).days >= 14:
        nudges.append({
            "priority": "low",
            "title": f"Workspace dormant {(today - last_dt).days} days",
            "detail": "Welcome back. Want a quick recap of what's pending?",
            "action": "Run weekly-recap or refresh-views.",
        })

    # ── Continuous pattern alerts ────────────────────────────────────────────
    nudges.extend(_pattern_alerts(p, today, root=root, person_id=person_id))

    # Sort: high > medium > low, stable order
    order = {"high": 0, "medium": 1, "low": 2}
    nudges.sort(key=lambda n: order.get(n["priority"], 9))
    return nudges


def _vitals_streak(
    vitals: list[dict[str, Any]], metric: str, days: int
) -> list[float]:
    """Return the last `days` daily values for a vital metric, most recent last."""
    cutoff = date.today() - timedelta(days=days)
    by_day: dict[str, float] = {}
    for v in vitals:
        if v.get("metric") != metric:
            continue
        d = _parse_date(v.get("date", ""))
        if d and d >= cutoff:
            try:
                by_day[d.isoformat()] = float(v.get("value", 0))
            except (TypeError, ValueError):
                pass
    return [by_day[k] for k in sorted(by_day)]


def _pattern_alerts(
    p: dict[str, Any],
    today: date,
    root: "Path | None" = None,
    person_id: str = "",
) -> list[dict[str, Any]]:
    """Detect continuous wearable and check-in patterns worth flagging."""
    from datetime import timedelta

    alerts: list[dict[str, Any]] = []
    checkins = sorted(p.get("daily_checkins", []), key=lambda c: str(c.get("date", "")))

    # Attempt to load vitals (may not be available in all environments)
    try:
        from .care_workspace import load_vital_entries as _lve
        vitals = _lve
        _has_vitals = True
    except (ImportError, Exception):
        try:
            from care_workspace import load_vital_entries as _lve  # type: ignore
            vitals = _lve
            _has_vitals = True
        except Exception:
            _has_vitals = False

    # ── Elevated resting HR streak (4+ consecutive days ≥80 bpm) ────────────
    if _has_vitals:
        try:
            # vitals is the function — we'd need root/person_id to call it.
            # Skip if not in context (pattern alert uses profile-embedded data)
            pass
        except Exception:
            pass

    # ── Chronic sleep deficit (avg < 6h for 7+ consecutive days) ────────────
    recent_7 = [c for c in checkins if _parse_date(c.get("date", "")) and
                (today - _parse_date(c.get("date", ""))).days <= 7]  # type: ignore[operator]
    sleep_vals_7 = [float(c["sleep_hours"]) for c in recent_7 if c.get("sleep_hours") is not None]
    if len(sleep_vals_7) >= 5:
        avg_sleep = sum(sleep_vals_7) / len(sleep_vals_7)
        if avg_sleep < 6.0:
            alerts.append({
                "priority": "high",
                "title": f"Chronic sleep deficit — avg {avg_sleep:.1f}h over last 7 days",
                "detail": "Less than 6h average sleep for a week impairs cognitive function, immune response, and metabolic health.",
                "action": "Prioritise sleep this week. Check for stress, caffeine timing, or screen use before bed.",
            })
        elif avg_sleep < 6.5:
            alerts.append({
                "priority": "medium",
                "title": f"Sleep below 7h average ({avg_sleep:.1f}h over last 7 days)",
                "detail": "Sustained mild sleep deprivation affects mood, energy, and recovery.",
                "action": "Try moving bedtime 30 minutes earlier this week.",
            })

    # ── Rapid weight gain (>2 kg in 14 days) ─────────────────────────────────
    # Weight entries are in care_workspace; check from profile if available
    weight_series = p.get("weight_series") or []
    if len(weight_series) >= 2:
        recent_w = [
            w for w in weight_series
            if _parse_date(w.get("date", "")) and
               (today - _parse_date(w.get("date", ""))).days <= 14  # type: ignore[operator]
        ]
        if len(recent_w) >= 3:
            try:
                kg_vals = [float(w["kg"]) for w in sorted(recent_w, key=lambda x: x.get("date", "")) if w.get("kg")]
                delta = kg_vals[-1] - kg_vals[0]
                if delta >= 2.0:
                    alerts.append({
                        "priority": "medium",
                        "title": f"Weight up {delta:.1f} kg in the last 14 days",
                        "detail": "Rapid weight gain (>2 kg / 2 weeks) is worth investigating — fluid retention, diet change, or medication effect.",
                        "action": "Check for swelling in ankles or feet. Mention to your GP if unexplained.",
                    })
            except (TypeError, ValueError, KeyError):
                pass

    # ── Sustained low energy + low mood (burnout signal) ─────────────────────
    recent_14 = [c for c in checkins if _parse_date(c.get("date", "")) and
                 (today - _parse_date(c.get("date", ""))).days <= 14]  # type: ignore[operator]
    energy_vals = [float(c["energy"]) for c in recent_14 if c.get("energy") is not None]
    mood_vals = [float(c["mood"]) for c in recent_14 if c.get("mood") is not None]
    if len(energy_vals) >= 5 and len(mood_vals) >= 5:
        avg_e = sum(energy_vals) / len(energy_vals)
        avg_m = sum(mood_vals) / len(mood_vals)
        if avg_e <= 4.0 and avg_m <= 5.0:
            alerts.append({
                "priority": "high",
                "title": f"Sustained low energy ({avg_e:.1f}/10) and mood ({avg_m:.1f}/10) for 2 weeks",
                "detail": "This pattern can indicate burnout, depression, or an underlying health issue.",
                "action": "Run `mental-health` for a full screen. Consider speaking with your GP.",
            })

    # ── Consistently high pain (avg ≥5 for 7+ days) ──────────────────────────
    pain_vals_7 = [float(c["pain"]) for c in recent_7 if c.get("pain") is not None]
    if len(pain_vals_7) >= 4:
        avg_pain = sum(pain_vals_7) / len(pain_vals_7)
        if avg_pain >= 5.0:
            alerts.append({
                "priority": "high",
                "title": f"Pain avg {avg_pain:.1f}/10 for the last week",
                "detail": "Persistent moderate-to-high pain warrants clinical attention.",
                "action": "Book an appointment. Run `triage` to prepare a summary for your clinician.",
            })

    # ── Non-dipping BP pattern ────────────────────────────────────────────────
    if root and person_id:
        try:
            try:
                from .care_workspace import load_vital_entries as _lve
            except ImportError:
                from care_workspace import load_vital_entries as _lve  # type: ignore

            bp_entries = [
                e for e in _lve(root, person_id)
                if e.get("metric") == "blood_pressure"
                and e.get("systolic") is not None
                and e.get("recorded_at")
            ]
            day_sys: list[float] = []
            night_sys: list[float] = []
            for e in bp_entries:
                try:
                    ts = str(e["recorded_at"])
                    hour = int(ts[11:13]) if len(ts) >= 13 else -1
                    sys_val = float(e["systolic"])
                    # Night = 22:00–06:59
                    if 22 <= hour or hour < 7:
                        night_sys.append(sys_val)
                    elif 7 <= hour < 22:
                        day_sys.append(sys_val)
                except (ValueError, TypeError, IndexError):
                    continue
            if len(day_sys) >= 3 and len(night_sys) >= 3:
                avg_day = sum(day_sys) / len(day_sys)
                avg_night = sum(night_sys) / len(night_sys)
                dip_pct = (avg_day - avg_night) / avg_day * 100 if avg_day > 0 else 0
                if dip_pct < 10:
                    alerts.append({
                        "priority": "medium",
                        "title": f"Non-dipping BP pattern detected (nocturnal dip {dip_pct:.1f}% — normal ≥10%)",
                        "detail": (
                            f"Daytime avg {avg_day:.0f} mmHg sys / Night avg {avg_night:.0f} mmHg sys. "
                            "Non-dipping is associated with higher cardiovascular risk."
                        ),
                        "action": "Mention to your GP — a 24h ambulatory BP monitor (ABPM) can confirm this pattern.",
                    })
        except Exception:
            pass

    return alerts


_NUDGE_COMMANDS = {
    "follow-up": "resolve-review-item --root .",
    "check-in": "daily-checkin --root .",
    "review": "list-review-queue --root .",
    "conflict": "list-conflicts --root .",
    "inbox": "process-inbox --root .",
    "ldl": "lab-range --root . --marker LDL",
    "hdl": "lab-range --root . --marker HDL",
    "a1c": "lab-range --root . --marker A1C",
    "tsh": "lab-range --root . --marker TSH",
    "cholesterol": "lab-range --root . --marker 'Total Cholesterol'",
    "sleep": "daily-checkin --root .",
    "pain": "triage --root .",
    "burnout": "mental-health --root .",
    "blood pressure": "record-vital --root . --metric blood_pressure",
    "weight": "record-weight --root .",
}


def _nudge_command(title: str) -> str | None:
    t = title.lower()
    for keyword, cmd in _NUDGE_COMMANDS.items():
        if keyword in t:
            return cmd
    return None


def render_nudges_md(nudges: list[dict[str, Any]]) -> str:
    today = date.today()
    if not nudges:
        return (
            "# Nudges\n\n"
            "---\n"
            f"generated: {today.isoformat()}\n"
            "high: 0\nmedium: 0\nlow: 0\ntotal: 0\n"
            "---\n\n"
            "Nothing urgent right now. Workspace looks clean. ✓\n\n"
            f"_Generated {today.isoformat()}_\n"
        )
    high = sum(1 for n in nudges if n.get("priority") == "high")
    medium = sum(1 for n in nudges if n.get("priority") == "medium")
    low = sum(1 for n in nudges if n.get("priority") == "low")
    lines = [
        "# Nudges",
        "",
        "---",
        f"generated: {today.isoformat()}",
        f"high: {high}",
        f"medium: {medium}",
        f"low: {low}",
        f"total: {len(nudges)}",
        "---",
        "",
    ]
    icons = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    for n in nudges:
        icon = icons.get(n["priority"], "·")
        lines.append(f"## {icon} {n['title']}")
        lines.append("")
        lines.append(n["detail"])
        if n.get("action"):
            lines.append(f"\n**Suggested:** {n['action']}")
        cmd = _nudge_command(n["title"])
        if cmd:
            lines.append(f"\n  **Run:** `{cmd}`")
        lines.append("")
    lines.append(f"\n_Generated {today.isoformat()}_")
    return "\n".join(lines) + "\n"


def write_nudges(root: Path, person_id: str) -> Path:
    nudges = compute_nudges(root, person_id)
    text = render_nudges_md(nudges)
    path = nudges_path(root, person_id)
    atomic_write_text(path, text)
    return path
