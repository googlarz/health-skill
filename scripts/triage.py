#!/usr/bin/env python3
"""Structured symptom triage.

Walks the user through 5 questions and produces:
- Urgency band (Emergency now / Urgent same day / Routine soon / Education only)
- Red flag check
- Drafted clinician handoff text

Used by Claude when the user describes a symptom. Claude can run interactively
(asking the questions in chat) or accept all answers in one batch via the CLI.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import atomic_write_text, triage_path
except ImportError:
    from care_workspace import atomic_write_text, triage_path  # type: ignore


# Red flags by region. Match against symptom + extras text.
RED_FLAGS = [
    # Cardiac / chest
    (re.compile(r"chest pain.*(?:pressure|crushing|radiating|jaw|left arm)|chest tightness with shortness of breath", re.I),
     "Possible cardiac event — call emergency services now."),
    # Stroke
    (re.compile(r"face droop|slurred speech|sudden weakness one side|trouble speaking suddenly|sudden vision loss", re.I),
     "Possible stroke — call emergency services now (FAST)."),
    # Anaphylaxis
    (re.compile(r"throat (?:closing|swelling)|tongue swelling|difficulty breathing.*allerg|wheezing.*food", re.I),
     "Possible anaphylaxis — use EpiPen if available, call emergency services."),
    # Severe headache
    (re.compile(r"worst headache|thunderclap|severe headache.*(?:vomiting|stiff neck|fever)", re.I),
     "Severe sudden headache — urgent evaluation required."),
    # Bleeding / pregnancy
    (re.compile(r"heavy bleeding|hemorrhag", re.I),
     "Uncontrolled bleeding — urgent care or ER."),
    (re.compile(r"pregnant.*(?:bleeding|severe pain|reduced fetal movement)", re.I),
     "Pregnancy with concerning symptoms — contact OB urgently."),
    # Mental health
    (re.compile(r"suicid|self.harm|kill myself|end my life", re.I),
     "Crisis — call 988 (US) or local crisis line. You're not alone."),
    # Sepsis
    (re.compile(r"high fever.*(?:confusion|low blood pressure|rapid heart)|septic", re.I),
     "Possible sepsis — emergency evaluation."),
    # Postmenopausal bleeding
    (re.compile(r"postmenopausal bleeding|bleeding after menopause", re.I),
     "Postmenopausal bleeding — needs gynecology evaluation soon."),
    # DVT
    (re.compile(r"unilateral leg (?:swelling|pain)|calf swelling.*HRT", re.I),
     "Possible DVT — urgent evaluation."),
]


# 5-question structured flow
TRIAGE_QUESTIONS = [
    "1. What's the symptom and where? (e.g. 'sharp pain, lower right belly')",
    "2. When did it start, and is it getting worse, better, or staying the same?",
    "3. Severity 1–10, and is it constant or comes and goes?",
    "4. Anything that makes it better or worse? (movement, food, position)",
    "5. Other symptoms with it? (fever, nausea, dizziness, rash, breathing)",
]


def assess(answers: dict[str, str]) -> dict[str, Any]:
    """Take answers dict (keys q1..q5) and return urgency assessment."""
    combined = " ".join(str(v) for v in answers.values()).lower()
    flags: list[str] = []
    for pat, msg in RED_FLAGS:
        if pat.search(combined):
            flags.append(msg)

    # Severity heuristic
    severity = 0
    m = re.search(r"\b(\d+)\s*/\s*10\b", combined)
    if m:
        severity = int(m.group(1))
    elif "worst" in combined or "unbearable" in combined:
        severity = 10

    # Trajectory
    worsening = any(w in combined for w in ("getting worse", "worsening", "progressing", "increasing"))

    # Determine band
    if flags:
        band = "Emergency now"
    elif severity >= 8 and worsening:
        band = "Urgent same day"
    elif severity >= 6 or worsening:
        band = "Urgent same day"
    elif severity >= 3:
        band = "Routine soon"
    else:
        band = "Education only"

    return {
        "band": band,
        "red_flags": flags,
        "severity": severity,
        "worsening": worsening,
        "answers": answers,
    }


def render_triage_md(symptom_summary: str, assessment: dict[str, Any]) -> str:
    band = assessment["band"]
    band_icon = {
        "Emergency now": "🚨",
        "Urgent same day": "🟠",
        "Routine soon": "🟡",
        "Education only": "🟢",
    }.get(band, "·")

    lines = [f"# Triage: {symptom_summary or 'symptom'}", ""]
    lines.append(f"**Urgency: {band_icon} {band}**")
    lines.append("")

    if assessment["red_flags"]:
        lines.append("## ⚠ Red flags detected")
        for f in assessment["red_flags"]:
            lines.append(f"- {f}")
        lines.append("")

    lines.append("## Your answers")
    for q_key, q_text in zip(["q1", "q2", "q3", "q4", "q5"], TRIAGE_QUESTIONS):
        ans = assessment["answers"].get(q_key, "")
        if ans:
            lines.append(f"- **{q_text.split('.', 1)[1].strip()}**")
            lines.append(f"  {ans}")
    lines.append("")

    lines.append("## Suggested handoff text")
    lines.append("")
    lines.append("```")
    lines.append(f"Reason for visit: {symptom_summary}")
    if assessment["answers"].get("q1"):
        lines.append(f"Description: {assessment['answers']['q1']}")
    if assessment["answers"].get("q2"):
        lines.append(f"Onset/course: {assessment['answers']['q2']}")
    if assessment["answers"].get("q3"):
        lines.append(f"Severity: {assessment['answers']['q3']}")
    if assessment["answers"].get("q4"):
        lines.append(f"Modifiers: {assessment['answers']['q4']}")
    if assessment["answers"].get("q5"):
        lines.append(f"Associated symptoms: {assessment['answers']['q5']}")
    lines.append("```")
    lines.append("")
    lines.append(f"_Generated {date.today().isoformat()}_")
    lines.append("")
    lines.append("**Health Skill is not a clinician.** This is structured triage, not diagnosis.")
    return "\n".join(lines) + "\n"


def write_triage(root: Path, person_id: str, summary: str, answers: dict[str, str]) -> Path:
    assessment = assess(answers)
    text = render_triage_md(summary, assessment)
    slug = re.sub(r"[^a-z0-9-]+", "-", summary.lower())[:40].strip("-") or "symptom"
    path = triage_path(root, person_id, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    return path
