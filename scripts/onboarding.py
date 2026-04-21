#!/usr/bin/env python3
"""First-session onboarding flow.

Generates ONBOARDING.md tailored for new users or returning users.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        changes_since_last_session,
        load_profile,
        onboarding_path,
    )
except ImportError:
    from care_workspace import (
        atomic_write_text,
        changes_since_last_session,
        load_profile,
        onboarding_path,
    )


NEW_USER_TEMPLATE = """# Welcome to your Health workspace, {name}

I'm here to be your longevity companion — not just a records tool. I connect your labs, training, mood, sleep, nutrition, and everything else so we can spot patterns and help you live better, longer.

## What I can help with

### Medical documents
Lab reports (MyChart/Quest/LabCorp), after-visit summaries, prescriptions, imaging reports
- Drop into `inbox/` — I'll extract and organize

### Photos
Medication bottles, skin changes, wounds, food, progress photos
- Drop into `inbox/` — I'll describe or OCR

### Training & fitness
- Design training plans for your goals (posture, strength, endurance, rehab)
- Log workouts naturally ("5k in 28 min", "bench 80kg 5x5")
- Track PRs and progression
- Build programs around your schedule and equipment
- Tell me: "I want to fix my posture, 3x30min/week with dumbbells"

### Daily check-ins
Mood, weight, sleep, energy, pain, stress — just tell me naturally
- "slept 6 hours, mood 7, back hurts 3/10"

### Cycle tracking (private, local-only)
Periods, symptoms, ovulation, patterns
- "period started today, cramps, heavy flow"

### Preventive care
I'll track what screenings you're due for based on your age and history
- "last mammogram was 2023-06"

### Questions I can answer
- "What do my labs mean in context of my training?"
- "Should I worry about this medication side effect?"
- "How's my period been this year?"
- "What's my sleep doing to my recovery?"
- "What am I overdue for?"

## Let's start — pick ONE:

1. **A concern** — what's on your mind health-wise?
2. **A goal** — training goal, weight goal, longevity goal?
3. **A document** — drop a lab report or visit note in `inbox/`
4. **A check-in** — how are you feeling today?
5. **Your basics** — medications, conditions, allergies, recent screenings
"""


RETURNING_USER_TEMPLATE = """# Welcome back, {name}

Here's what I'm seeing since we last talked:
{diff_lines}

Pick up where you left off, or ask me anything.
"""


def _format_session_diff(diff: dict[str, Any]) -> str:
    if not diff.get("last_session"):
        return "- (this looks like your first active session in a while — no prior checkpoint)"

    lines = []
    days_ago = diff.get("days_ago")
    if days_ago is not None:
        if days_ago < 1:
            lines.append(f"- Last session: {days_ago*24:.1f} hours ago")
        else:
            lines.append(f"- Last session: {days_ago} days ago")
    if diff.get("new_documents"):
        lines.append(f"- {diff['new_documents']} new document(s) added")
    if diff.get("new_notes"):
        lines.append(f"- {diff['new_notes']} new note(s)")
    if diff.get("profile_changes"):
        lines.append(f"- Profile updated in: {', '.join(diff['profile_changes'])}")
    if diff.get("new_review_items"):
        lines.append(f"- {diff['new_review_items']} item(s) awaiting your review")
    if diff.get("resolved_items"):
        lines.append(f"- {diff['resolved_items']} item(s) resolved since last time")

    if not lines:
        lines.append("- Nothing changed since last session")
    return "\n".join(lines)


def render_onboarding_text(profile: dict[str, Any], has_any_data: bool, session_diff: dict[str, Any] | None = None) -> str:
    name = profile.get("name") or "there"
    if not has_any_data:
        return NEW_USER_TEMPLATE.format(name=name)
    diff_lines = _format_session_diff(session_diff or {})
    return RETURNING_USER_TEMPLATE.format(name=name, diff_lines=diff_lines)


def _profile_has_data(profile: dict[str, Any]) -> bool:
    for key in (
        "conditions", "medications", "allergies", "recent_tests",
        "daily_checkins", "cycles", "workouts", "screenings",
        "documents", "encounters",
    ):
        if profile.get(key):
            return True
    return False


def command_onboard(root: Path, person_id: str) -> Path:
    """Render onboarding text to ONBOARDING.md and return the path."""
    profile = load_profile(root, person_id)
    has_data = _profile_has_data(profile)
    try:
        diff = changes_since_last_session(root, person_id)
    except Exception:
        diff = {}
    text = render_onboarding_text(profile, has_data, diff)
    path = onboarding_path(root, person_id)
    atomic_write_text(path, text)
    return path
