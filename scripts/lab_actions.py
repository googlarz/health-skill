#!/usr/bin/env python3
"""Lab-to-action engine.

For each abnormal lab in the profile, generate concrete next steps:
- Clinician question
- Lifestyle consideration (with safety wrap)
- Recommended follow-up cadence
- Drafted portal message

Output: LAB_ACTIONS.md after process-inbox or on demand.

Knowledge base is intentionally compact and conservative. We never tell users
to start, stop, or change prescription medications. We always defer treatment
decisions to clinicians.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        lab_actions_path,
        load_snapshot,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        lab_actions_path,
        load_snapshot,
    )


# Marker → action template
LAB_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "LDL": {
        "high": {
            "meaning": "Above-target LDL increases cardiovascular risk over time.",
            "lifestyle": "Strength training (3×/week) + soluble fiber (oats, beans, psyllium) + reduced saturated fat have evidence. Plant sterols can lower LDL ~5–10%.",
            "follow_up_months": 4,
            "questions": [
                "Given my LDL trend and ASCVD risk, do I meet criteria for a statin or alternative?",
                "Should we recheck lipids in 3–6 months and recalculate ASCVD risk?",
                "Is Lp(a) worth measuring once at baseline?",
            ],
        },
    },
    "HDL": {
        "low": {
            "meaning": "Low HDL is associated with higher cardiovascular risk.",
            "lifestyle": "Aerobic exercise (zone 2 + intervals), omega-3-rich foods, and avoiding trans fats can help. Smoking cessation matters most if relevant.",
            "follow_up_months": 6,
            "questions": [
                "Is my low HDL likely lifestyle, genetic, or secondary to something else?",
                "Should we look at total/HDL ratio and ApoB?",
            ],
        },
    },
    "A1C": {
        "high": {
            "meaning": "A1C reflects 3-month average blood sugar. Above-target values raise diabetes complication risk.",
            "lifestyle": "Resistance training, post-meal walks (10–15 min), reducing refined carbs, and protein at every meal have strong evidence.",
            "follow_up_months": 3,
            "questions": [
                "Is this prediabetes or diabetes range, and what's the recommended target for me?",
                "Should I add a fasting glucose or OGTT?",
                "Is metformin appropriate given my situation, or lifestyle-first?",
            ],
        },
    },
    "TSH": {
        "high": {
            "meaning": "Elevated TSH suggests the thyroid may be underactive (hypothyroid).",
            "lifestyle": "Lifestyle measures don't fix thyroid dysfunction — medication may be needed. Symptoms to track: fatigue, cold intolerance, weight, hair, mood.",
            "follow_up_months": 2,
            "questions": [
                "Should we add free T4 and TPO antibodies?",
                "Is my dose (if on levothyroxine) optimised given the trend?",
                "What's the recheck cadence given my symptoms?",
            ],
        },
        "low": {
            "meaning": "Low TSH suggests possible overactive thyroid or over-replacement.",
            "lifestyle": "If on thyroid medication, do not adjust dose without clinician input.",
            "follow_up_months": 1,
            "questions": [
                "Should we add free T4, free T3, and TSH receptor antibodies?",
                "Is my dose too high, or is this primary hyperthyroidism?",
            ],
        },
    },
    "Glucose": {
        "high": {
            "meaning": "Fasting glucose above range suggests prediabetes or diabetes.",
            "lifestyle": "Same as A1C: resistance training + post-meal walks + lower refined carbs + protein at meals.",
            "follow_up_months": 3,
            "questions": [
                "Should we confirm with A1C and fasting glucose?",
                "Are there other risk factors to address (BMI, family history, sleep)?",
            ],
        },
    },
    "Vitamin D": {
        "low": {
            "meaning": "Below ~30 ng/mL is generally considered insufficient. Affects bone, mood, and immunity.",
            "lifestyle": "Sun exposure (10–20 min midday on bare skin where safe). Discuss D3 supplementation dose with clinician — typical 1000–4000 IU/day depending on baseline.",
            "follow_up_months": 3,
            "questions": [
                "What dose of D3 should I take, and for how long before rechecking?",
                "Should we also check calcium and PTH?",
            ],
        },
    },
    "Triglycerides": {
        "high": {
            "meaning": "High triglycerides are linked to cardiovascular and pancreatic risk.",
            "lifestyle": "Reduce refined carbs and alcohol; omega-3s (fatty fish or supplement) reduce triglycerides at therapeutic doses; aerobic exercise helps.",
            "follow_up_months": 3,
            "questions": [
                "What is my non-HDL cholesterol and ApoB?",
                "Is this secondary to insulin resistance? Should we check fasting insulin?",
            ],
        },
    },
    "Total Cholesterol": {
        "high": {
            "meaning": "Total cholesterol alone is less informative than LDL, HDL, and ApoB.",
            "lifestyle": "Same lifestyle measures as LDL.",
            "follow_up_months": 4,
            "questions": [
                "What does ApoB show? It's a more direct atherogenic particle measure.",
                "Should we recalculate ASCVD 10-year risk?",
            ],
        },
    },
    "Creatinine": {
        "high": {
            "meaning": "Elevated creatinine may indicate reduced kidney filtration. Clinical context matters.",
            "lifestyle": "Hydration matters. Avoid NSAIDs without clinician input. Strenuous exercise within 24h can transiently raise creatinine.",
            "follow_up_months": 2,
            "questions": [
                "What is my eGFR and is it stable?",
                "Should we add a urine albumin/creatinine ratio?",
            ],
        },
    },
    "ALT": {
        "high": {
            "meaning": "Elevated ALT may indicate liver inflammation; common causes include fatty liver, alcohol, medications, viral hepatitis.",
            "lifestyle": "Reduce alcohol; review supplements (some are hepatotoxic); weight loss helps fatty liver.",
            "follow_up_months": 2,
            "questions": [
                "Should we recheck ALT and add AST, GGT, and a fatty-liver workup?",
                "Could any of my medications or supplements explain this?",
            ],
        },
    },
}


def _direction_for_marker(marker: str, flag: str) -> str | None:
    """Convert flag into our 'high' / 'low' bucket, if known."""
    flag = (flag or "").lower()
    if flag in ("high", "abnormal"):
        # Some abnormal flags are ambiguous — we'll trust 'high' default for most
        return "high"
    if flag == "low":
        return "low"
    return None


def actions_for_lab(test: dict[str, Any]) -> dict[str, Any] | None:
    """Generate an action bundle for one abnormal lab. None if not actionable."""
    name = str(test.get("name", "")).strip()
    flag = test.get("flag", "")
    if not flag or flag.lower() == "normal":
        return None
    # Match marker (case-insensitive prefix)
    knowledge = None
    matched_marker = None
    for marker, data in LAB_KNOWLEDGE.items():
        if name.upper() == marker.upper() or name.upper().startswith(marker.upper()):
            knowledge = data
            matched_marker = marker
            break
    if not knowledge:
        return None
    direction = _direction_for_marker(matched_marker or "", str(flag))
    if not direction or direction not in knowledge:
        return None
    info = knowledge[direction]
    return {
        "marker": matched_marker,
        "direction": direction,
        "value": test.get("value"),
        "unit": test.get("unit", ""),
        "date": test.get("date", ""),
        "meaning": info["meaning"],
        "lifestyle": info["lifestyle"],
        "follow_up_months": info["follow_up_months"],
        "questions": list(info["questions"]),
    }


def build_actions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return action bundles for the latest abnormal lab per marker."""
    # Pick the latest abnormal value per marker
    latest_per_marker: dict[str, dict[str, Any]] = {}
    for t in profile.get("recent_tests", []):
        name = str(t.get("name", "")).strip()
        if not name:
            continue
        d = str(t.get("date", ""))
        prev = latest_per_marker.get(name.upper())
        if not prev or str(prev.get("date", "")) < d:
            latest_per_marker[name.upper()] = t

    actions = []
    for t in latest_per_marker.values():
        a = actions_for_lab(t)
        if a:
            actions.append(a)
    return actions


def draft_portal_message(profile: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    """One concise, polite portal message covering all out-of-range labs."""
    if not actions:
        return ""
    name = profile.get("name") or "the patient"
    lines = [f"Hello,", "",
             f"My recent labs flagged the following:",
             ""]
    for a in actions:
        lines.append(f"- {a['marker']}: {a['value']} {a['unit']} ({a['direction']}) on {a['date']}")
    lines.append("")
    lines.append("I'd like to discuss:")
    seen_qs = set()
    for a in actions:
        for q in a["questions"][:1]:  # one question per marker keeps it focused
            if q not in seen_qs:
                lines.append(f"- {q}")
                seen_qs.add(q)
    lines.append("")
    lines.append("Could we either schedule a brief visit or address this through messages? Thank you.")
    return "\n".join(lines)


def render_lab_actions_md(profile: dict[str, Any]) -> str:
    actions = build_actions(profile)
    today = date.today()
    name = profile.get("name") or "You"
    lines = [f"# Lab Actions — {name}", "",
             f"_Generated {today.isoformat()}_", ""]
    if not actions:
        lines.append("✓ No actionable abnormal labs in current profile.")
        lines.append("")
        return "\n".join(lines) + "\n"

    lines.append("## What to do for each out-of-range result")
    lines.append("")
    for a in actions:
        eta = (today + timedelta(days=30 * a["follow_up_months"])).isoformat()
        lines.append(f"### {a['marker']} ({a['direction']}: {a['value']} {a['unit']})")
        lines.append("")
        lines.append(f"**Meaning:** {a['meaning']}")
        lines.append("")
        lines.append(f"**Lifestyle considerations:** {a['lifestyle']}")
        lines.append("")
        lines.append(f"**Recommended recheck:** ~{a['follow_up_months']} months ({eta})")
        lines.append("")
        lines.append("**Questions for your clinician:**")
        for q in a["questions"]:
            lines.append(f"- {q}")
        lines.append("")

    # Portal message
    portal = draft_portal_message(profile, actions)
    if portal:
        lines.append("## Drafted portal message")
        lines.append("")
        lines.append("```")
        lines.append(portal)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Important:** This is general health information based on your data, "
                 "not personalised medical advice. Always discuss with your clinician before "
                 "starting, stopping, or changing any medication.")
    return "\n".join(lines) + "\n"


def write_lab_actions(root: Path, person_id: str) -> Path:
    snap = load_snapshot(root, person_id)
    text = render_lab_actions_md(snap.profile)
    path = lab_actions_path(root, person_id)
    atomic_write_text(path, text)
    return path
