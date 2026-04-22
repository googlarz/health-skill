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

I'm your longevity companion — not just a records organizer. I connect your labs, training, mood, sleep, weight, hormones, and everything else to spot patterns and help you feel and perform better over time.

Everything stays on your device. Nothing is sent anywhere.

---

## What you can send me

### 📋 Medical documents
Drop any of these into `inbox/` and I'll extract the important data automatically:
- **Lab reports** — Quest, LabCorp, MyChart PDFs. I'll pull out every value, flag abnormals, and track trends over time. *Example: "LDL went from 188 → 162 → 141 — here's what that trend means"*
- **After-visit summaries** — I'll extract diagnoses, medications, and follow-up instructions
- **Discharge notes** — I'll build a checklist of what to do next
- **Prescription lists** — I'll check for allergy conflicts and flag anything to ask your pharmacist
- **Imaging reports** — I'll translate radiology language into plain English

### 📸 Photos you can send me
- **Posture photo** (side or back view) — I'll analyze your alignment, spot imbalances, and suggest corrective exercises
- **Skin changes or wounds** — I'll describe what I see and tell you when to see a doctor
- **Medication bottle** — I'll read the label, check interactions, and explain what it's for
- **Food photo** — rough macro estimate, protein check if you're tracking intake
- **Progress photo** — body composition notes over time

### 🏋️ Training & fitness
Tell me your goals and I'll build a personalised plan:
- *"Fix my posture, 3 days a week, 30 min, I have dumbbells"*
- *"Build strength for menopause, compound lifts, bad left knee"*
- *"Couch to 5k in 8 weeks"*
- *"Upper/lower split, 4 days, home gym"*

Log workouts naturally:
- *"45 min strength — squats 60kg 4x8, RDL 50kg 3x10, rows"*
- *"Easy 5k run, 28:30, felt good"*
- *"PT session, 30 min — bird dogs, dead bugs, wall angels"*

I track PRs, progression, and training load automatically.

### ⚖️ Daily weight
Just tell me:
- *"76.2 kg this morning"*
- *"weight 168 lbs"*

I'll track the trend, smooth out daily noise, and show you the actual direction — not just yesterday vs today.

### 😴 Daily check-in (mood, sleep, energy, pain)
One line is enough:
- *"slept 6 hours, mood 7/10, energy low, knee 3/10"*
- *"great day — 8h sleep, mood 9, no pain"*
- *"terrible night, hot flashes woke me twice, exhausted"*

Over time I connect these: sleep → next-day energy, cycle phase → mood, training load → pain.

### 🩸 Cycle tracking (opt-in, private)
- *"period started today, cramps, flow heavy"*
- *"spotting, day 14, slight cramping"*
- *"period ended, 5 days total"*

I predict your next period, track cycle length, and connect cycle phase to your mood and energy check-ins if you log both.

### 💊 Hormones & menopause
Tell me where you are and what you're experiencing:
- *"I'm 48, cycles getting irregular, hot flashes at night, brain fog"*
- *"Started estrogen patch 3 months ago, want to understand my labs"*
- *"What exercises are best for bone density post-menopause?"*

I'll explain FSH/LH/Estradiol/SHBG in plain language, explain how different HRT types work, and tell you what questions to bring to your clinician.

### 🩺 Preventive care
Tell me what you've had done and I'll track what's due next:
- *"Last mammogram June 2023"*
- *"Colonoscopy done 2020"*
- *"Never had a DEXA scan"*

---

## Questions I can answer right now

- *"What do my cholesterol labs mean and is the trend good?"*
- *"I'm starting metformin — what should I know?"*
- *"My LDL is 165 — does my training frequency affect that?"*
- *"Should I be worried about this symptom?"*
- *"Help me prepare for my appointment on Thursday"*
- *"What's overdue for me this year?"*
- *"Write a message I can send my doctor through the portal"*

---

---

**What would you like to share or start with today?**

You can drop a photo or document (like lab results) right here in the chat, tell me how you're feeling, share a goal, or just ask a question — whatever feels most useful right now.
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
