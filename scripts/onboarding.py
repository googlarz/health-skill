#!/usr/bin/env python3
"""First-session onboarding flow.

Generates ONBOARDING.md tailored for new users or returning users.

New user flow: a prioritised questionnaire. Claude works through questions one
at a time, explaining WHY each piece of data matters before asking for it.

Returning user flow: a brief diff of what changed + a nudge toward the most
impactful data still missing.
"""

from __future__ import annotations

from datetime import date, datetime
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
    from care_workspace import (  # type: ignore
        atomic_write_text,
        changes_since_last_session,
        load_profile,
        onboarding_path,
    )


# ---------------------------------------------------------------------------
# Questionnaire definition
# Each item: (field_key, label, ask, why, example, impact 1-3)
# impact 3 = highest — shown first, asked first
# ---------------------------------------------------------------------------

QUESTIONNAIRE: list[dict[str, Any]] = [
    # ── Foundation ──────────────────────────────────────────────────────────
    {
        "key": "date_of_birth",
        "label": "Date of birth",
        "ask": "What's your date of birth?",
        "why": (
            "Age changes what's normal for almost every lab value "
            "and determines which preventive screenings you need and when."
        ),
        "example": "1978-06-14",
        "impact": 3,
    },
    {
        "key": "sex",
        "label": "Biological sex",
        "ask": "What's your biological sex? (male / female)",
        "why": (
            "Lab reference ranges for cholesterol, hormones, iron, and dozens of "
            "other markers differ by sex. It also drives the preventive screening schedule "
            "(mammogram, cervical cancer, PSA, bone density)."
        ),
        "example": "female",
        "impact": 3,
    },
    # ── Health history ───────────────────────────────────────────────────────
    {
        "key": "conditions",
        "label": "Current diagnoses",
        "ask": (
            "Do you have any diagnosed conditions I should know about? "
            "List as many or as few as you'd like — you can always add more later."
        ),
        "why": (
            "Conditions change how I read your labs. Diabetes means your HbA1c, "
            "kidney function, and LDL are read differently. Hypothyroidism means "
            "I watch your TSH trend closely. PCOS changes how I interpret hormones."
        ),
        "example": "type 2 diabetes, hypothyroidism, PCOS",
        "impact": 3,
    },
    {
        "key": "allergies",
        "label": "Drug allergies",
        "ask": "Do you have any drug or food allergies?",
        "why": (
            "This is the most important safety check. If you ever add a new "
            "medication, I flag it immediately if it conflicts with a known allergy — "
            "before you take it."
        ),
        "example": "penicillin (rash), sulfa drugs",
        "impact": 3,
    },
    {
        "key": "medications",
        "label": "Current medications",
        "ask": (
            "What medications are you currently taking? Include prescription drugs, "
            "supplements, and anything you take regularly."
        ),
        "why": (
            "I track interactions between your medications and any new prescriptions. "
            "Some supplements interfere with lab results (biotin skews thyroid tests, "
            "fish oil affects bleeding time). I also monitor for known side effects "
            "in your check-in data."
        ),
        "example": "metformin 1000mg, levothyroxine 75mcg, vitamin D 2000 IU",
        "impact": 3,
    },
    # ── Labs ─────────────────────────────────────────────────────────────────
    {
        "key": "recent_tests",
        "label": "Recent lab results",
        "ask": (
            "Do you have any recent lab results? You can paste values, "
            "drop a PDF into the inbox folder, or just tell me the date of "
            "your last blood panel — even a rough date is useful."
        ),
        "why": (
            "Labs are the core of what I track. Even one data point gives me a "
            "baseline to compare against. Three or more gives me a trend — and "
            "trends are far more meaningful than a single result. I'll flag "
            "anything out of range and tell you what it means."
        ),
        "example": "LDL 165, HDL 52, glucose 94 (March 2024)",
        "impact": 3,
    },
    # ── Family history ───────────────────────────────────────────────────────
    {
        "key": "family_history",
        "label": "Family health history",
        "ask": (
            "Any significant health conditions in your immediate family "
            "(parents, siblings)? Especially cancer, heart disease, diabetes, "
            "or early deaths."
        ),
        "why": (
            "Family history directly changes your screening schedule. "
            "If your mother had breast cancer at 48, I'll suggest starting "
            "mammograms at 38 instead of 40. A parent's heart attack before 55 "
            "moves your lipid panel start date earlier."
        ),
        "example": "mother: breast cancer at 48, father: heart attack at 58",
        "impact": 2,
    },
    # ── Goals ────────────────────────────────────────────────────────────────
    {
        "key": "goals",
        "label": "Health goals",
        "ask": (
            "What are your main health goals right now? Don't overthink it — "
            "one sentence is enough."
        ),
        "why": (
            "Goals shape everything I recommend. 'Lower my LDL' leads to "
            "different suggestions than 'build bone density' or 'sleep better'. "
            "I'll also track your progress toward each goal automatically."
        ),
        "example": "get LDL under 130, build strength, improve sleep quality",
        "impact": 2,
    },
    # ── Cycle / hormones ─────────────────────────────────────────────────────
    {
        "key": "cycle",
        "label": "Cycle / hormonal health",
        "ask": (
            "Would you like to track your menstrual cycle, or are you in "
            "perimenopause or menopause? (This is entirely opt-in and optional.)"
        ),
        "why": (
            "Cycle phase affects energy, mood, pain tolerance, and training "
            "recovery. If you log daily check-ins, I'll connect cycle phase to "
            "your data automatically — 'you consistently feel worse on days 1-2'. "
            "For perimenopause/menopause, I have specific knowledge on hormones, "
            "HRT options, and bone-protective exercise."
        ),
        "example": "cycles regular, 28 days / perimenopause, last period 6 months ago",
        "impact": 2,
    },
    # ── Preventive care ──────────────────────────────────────────────────────
    {
        "key": "screenings",
        "label": "Preventive screenings",
        "ask": (
            "When did you last have key screenings? Tell me whatever you remember — "
            "mammogram, colonoscopy, Pap smear, DEXA scan, skin check, eye exam, "
            "dental. Rough dates are fine."
        ),
        "why": (
            "I track what's due and what's overdue. If you've never had a DEXA "
            "scan and you're post-menopausal, I'll flag it. I adjust all dates "
            "based on your age, sex, and family history."
        ),
        "example": "mammogram June 2023, Pap 2021, no colonoscopy yet",
        "impact": 2,
    },
    # ── Wearables / daily habits ─────────────────────────────────────────────
    {
        "key": "wearable",
        "label": "Fitness tracker",
        "ask": (
            "Do you use a fitness watch or tracker? "
            "(Apple Watch, Garmin, Whoop, Oura, Polar, Suunto, Fitbit, etc.)"
        ),
        "why": (
            "Daily data reveals patterns that quarterly labs miss. Resting heart "
            "rate trends, sleep quality, HRV, and step count together paint a "
            "picture of recovery and cardiovascular health. I can set up automatic "
            "sync so this data flows in without you lifting a finger."
        ),
        "example": "Apple Watch Series 9",
        "impact": 1,
    },
]


# ---------------------------------------------------------------------------
# Completion scoring
# ---------------------------------------------------------------------------

def _profile_completeness(profile: dict[str, Any]) -> dict[str, Any]:
    """Score how complete the profile is across key dimensions."""

    def _has(key: str) -> bool:
        val = profile.get(key)
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)

    checks = {
        "date_of_birth": _has("date_of_birth"),
        "sex":           _has("sex"),
        "conditions":    _has("conditions"),
        "allergies":     _has("allergies"),
        "medications":   _has("medications"),
        "recent_tests":  _has("recent_tests"),
        "family_history": _has("family_history"),
        "goals":         _has("goals"),
        "screenings":    _has("screenings"),
        "daily_checkins": _has("daily_checkins"),
    }
    filled = sum(1 for v in checks.values() if v)
    total = len(checks)
    pct = int(filled / total * 100)

    bar_filled = filled * 2
    bar_empty = (total - filled) * 2
    bar = "█" * bar_filled + "░" * bar_empty

    return {
        "checks": checks,
        "filled": filled,
        "total": total,
        "pct": pct,
        "bar": bar,
    }


def _missing_questions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return questionnaire items for fields that are empty, sorted by impact desc."""

    def _is_filled(key: str) -> bool:
        # Special cases
        if key == "cycle":
            prefs = profile.get("preferences", {}) or {}
            return (
                prefs.get("track_cycles") is not None
                or bool(profile.get("cycles"))
            )
        if key == "wearable":
            prefs = profile.get("preferences", {}) or {}
            return bool(prefs.get("wearable_type"))
        val = profile.get(key)
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)

    missing = [q for q in QUESTIONNAIRE if not _is_filled(q["key"])]
    return sorted(missing, key=lambda q: -q["impact"])


def _labs_stale(profile: dict[str, Any], months: int = 12) -> bool:
    """True if the most recent lab is older than `months` months."""
    tests = profile.get("recent_tests") or []
    if not tests:
        return False
    dates = []
    for t in tests:
        raw = t.get("date") or ""
        try:
            dates.append(datetime.strptime(raw[:10], "%Y-%m-%d").date())
        except ValueError:
            pass
    if not dates:
        return False
    newest = max(dates)
    months_ago = (date.today() - newest).days / 30
    return months_ago > months


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

INTRO = """# Welcome to your Health workspace{name_part}

I'm your longevity companion — not just a records organizer.

I connect your labs, training, mood, sleep, weight, hormones, and family history to spot patterns over time and help you get more out of every doctor's visit. Everything stays on your device. Nothing is sent anywhere.

To get started I'll ask you a few questions. Each one unlocks something specific — I'll tell you why I'm asking before I ask it. You can skip anything you're not ready to share.

"""

COMPLETION_HEADER = "## Profile completeness: {pct}% [{bar}]\n\n"

QUESTIONNAIRE_INTRO = """## What I still need from you

Below is your personalised questionnaire, sorted by impact. I'll work through these with you one at a time.

"""

QUESTION_BLOCK = """### {n}. {label}
**Why this matters:** {why}

**Question:** {ask}

*Example: {example}*

"""

RETURNING_TEMPLATE = """# Welcome back{name_part}

{diff_lines}

---

## Profile: {pct}% complete [{bar}]

{gap_section}"""


def _render_gap_section(missing: list[dict[str, Any]], labs_stale: bool) -> str:
    if not missing and not labs_stale:
        return "✅ Your profile looks complete. Nothing critical is missing.\n"

    lines = []
    if labs_stale:
        lines.append(
            "⚠️ **Labs are overdue** — your most recent results are more than "
            "12 months old. Ask me to help you prepare a lab order or understand "
            "what to request at your next visit.\n"
        )

    if missing:
        lines.append("**Still missing (highest impact first):**\n")
        for i, q in enumerate(missing[:3], 1):
            lines.append(f"{i}. **{q['label']}** — {q['why']}")
        if len(missing) > 3:
            lines.append(
                f"\n…and {len(missing) - 3} more. Ask me "
                f"\"what else do you need from me?\" to see the full list."
            )

    return "\n".join(lines) + "\n"


def render_onboarding_text(
    profile: dict[str, Any],
    has_any_data: bool,
    session_diff: dict[str, Any] | None = None,
) -> str:
    name = profile.get("name") or ""
    name_part = f", {name}" if name else ""
    completeness = _profile_completeness(profile)
    missing = _missing_questions(profile)
    stale = _labs_stale(profile)

    if not has_any_data:
        # ── New user ──────────────────────────────────────────────────────
        text = INTRO.format(name_part=name_part)
        text += COMPLETION_HEADER.format(
            pct=completeness["pct"], bar=completeness["bar"]
        )

        if missing:
            text += QUESTIONNAIRE_INTRO
            for i, q in enumerate(missing, 1):
                text += QUESTION_BLOCK.format(
                    n=i,
                    label=q["label"],
                    why=q["why"],
                    ask=q["ask"],
                    example=q["example"],
                )

        text += (
            "---\n\n"
            "**How this works:** I'll ask you these questions one at a time in our conversation — "
            "you don't need to fill them all in at once. You can also just drop a lab PDF into "
            "the inbox folder and I'll extract the data automatically.\n\n"
            "**Ready? Let's start with the first question above.**\n"
        )
        return text

    # ── Returning user ────────────────────────────────────────────────────
    diff_lines = _format_session_diff(session_diff or {})
    gap_section = _render_gap_section(missing, stale)
    return RETURNING_TEMPLATE.format(
        name_part=name_part,
        diff_lines=diff_lines,
        pct=completeness["pct"],
        bar=completeness["bar"],
        gap_section=gap_section,
    )


def _format_session_diff(diff: dict[str, Any]) -> str:
    if not diff.get("last_session"):
        return "_No prior session checkpoint found._"

    lines = []
    days_ago = diff.get("days_ago")
    if days_ago is not None:
        if days_ago < 1:
            lines.append(f"- Last session: {days_ago * 24:.1f} hours ago")
        else:
            days_ago_int = int(days_ago)
            lines.append(f"- Last session: {days_ago_int} day{'s' if days_ago_int != 1 else ''} ago")
    if diff.get("new_documents"):
        lines.append(f"- {diff['new_documents']} new document(s) added since then")
    if diff.get("new_notes"):
        lines.append(f"- {diff['new_notes']} new note(s)")
    if diff.get("profile_changes"):
        lines.append(f"- Profile updated: {', '.join(diff['profile_changes'])}")
    if diff.get("new_review_items"):
        lines.append(f"- {diff['new_review_items']} item(s) waiting for your review")
    if diff.get("resolved_items"):
        lines.append(f"- {diff['resolved_items']} item(s) resolved")

    if not lines:
        lines.append("- Nothing changed since last session")
    return "\n".join(lines)


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
