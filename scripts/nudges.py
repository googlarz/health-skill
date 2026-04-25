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

    # Sort: high > medium > low, stable order
    order = {"high": 0, "medium": 1, "low": 2}
    nudges.sort(key=lambda n: order.get(n["priority"], 9))
    return nudges


def render_nudges_md(nudges: list[dict[str, Any]]) -> str:
    if not nudges:
        return (
            "# Nudges\n\n"
            "Nothing urgent right now. Workspace looks clean. ✓\n\n"
            "_Generated " + date.today().isoformat() + "_\n"
        )
    lines = ["# Nudges\n"]
    icons = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    for n in nudges:
        icon = icons.get(n["priority"], "·")
        lines.append(f"## {icon} {n['title']}")
        lines.append("")
        lines.append(n["detail"])
        if n.get("action"):
            lines.append(f"\n**Suggested:** {n['action']}")
        lines.append("")
    lines.append(f"\n_Generated {date.today().isoformat()}_")
    return "\n".join(lines) + "\n"


def write_nudges(root: Path, person_id: str) -> Path:
    nudges = compute_nudges(root, person_id)
    text = render_nudges_md(nudges)
    path = nudges_path(root, person_id)
    atomic_write_text(path, text)
    return path
