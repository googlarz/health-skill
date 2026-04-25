#!/usr/bin/env python3
"""Decision support — structured shared-decision-making aids.

Three flagship decisions:
1. HRT (perimenopause/menopause)
2. Statin (primary prevention)
3. Screening intensity (mammogram, colonoscopy cadence)

Each decision aid:
- Pulls relevant facts from the user's profile
- Computes a simple risk frame (no diagnostic claims)
- Surfaces pros/cons specific to their situation
- Lists what's missing to make the call
- Drafts questions to bring to the clinician

These are conversation tools, never recommendations.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        calculate_age_from_dob,
        decisions_dir,
        load_profile,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        calculate_age_from_dob,
        decisions_dir,
        load_profile,
    )


def _has_condition(profile: dict[str, Any], terms: list[str]) -> list[str]:
    """Return any condition names matching given terms."""
    out = []
    for c in profile.get("conditions", []):
        cname = str(c.get("name", "")).lower()
        for term in terms:
            if term in cname:
                out.append(c.get("name"))
                break
    return out


def _latest_test(profile: dict[str, Any], marker: str) -> dict[str, Any] | None:
    """Return latest entry matching marker (case-insensitive prefix)."""
    candidates = []
    for t in profile.get("recent_tests", []):
        name = str(t.get("name", "")).strip().upper()
        if name == marker.upper() or name.startswith(marker.upper()):
            candidates.append(t)
    candidates.sort(key=lambda t: str(t.get("date", "")))
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# HRT decision aid
# ---------------------------------------------------------------------------

HRT_CONTRAINDICATIONS = [
    "active breast cancer", "history of breast cancer", "endometrial cancer",
    "active liver disease", "active dvt", "active pulmonary embolism",
    "active stroke", "untreated coronary artery disease",
]


def hrt_decision(profile: dict[str, Any]) -> dict[str, Any]:
    age = calculate_age_from_dob(profile.get("date_of_birth", "")) or 0
    sex = str(profile.get("sex", "")).lower()
    symptoms = profile.get("daily_checkins", [])
    # Look at recent symptom keywords
    recent_text = " ".join(str(c.get("notes", "")) + " "
                           + " ".join(str(s) for s in (c.get("symptoms") or []))
                           for c in symptoms[-30:])
    has_hot_flashes = "hot flash" in recent_text.lower() or "night sweat" in recent_text.lower()
    has_sleep_issues = "insomnia" in recent_text.lower() or "can't sleep" in recent_text.lower()
    has_brain_fog = "brain fog" in recent_text.lower() or "foggy" in recent_text.lower()
    has_joint_pain = "joint pain" in recent_text.lower() or "achy" in recent_text.lower()

    contras = _has_condition(profile, HRT_CONTRAINDICATIONS)
    fsh = _latest_test(profile, "FSH")
    estradiol = _latest_test(profile, "Estradiol")

    has_uterus = "yes"  # We don't track this — flag as missing
    if any("hyster" in str(c.get("name", "")).lower() for c in profile.get("conditions", [])):
        has_uterus = "no"

    pros = []
    cons = []
    missing = []

    if sex != "female":
        return {
            "applicable": False,
            "reason": "HRT decision aid is currently scoped to perimenopausal/menopausal women.",
        }
    if age < 40 or age > 65:
        cons.append(f"Standard HRT timing is age 40–65; you are {age}.")

    # Symptoms supporting HRT
    if has_hot_flashes:
        pros.append("Hot flashes / night sweats are the strongest HRT-responsive symptom.")
    if has_sleep_issues:
        pros.append("Sleep disruption from vasomotor symptoms typically improves with HRT.")
    if has_brain_fog:
        pros.append("Brain fog may improve, especially in early menopause.")
    if has_joint_pain:
        pros.append("Estrogen-deficiency joint pain often responds to estrogen replacement.")

    # Bone protection
    pros.append("Reduces fracture risk and protects bone density (key benefit post-menopause).")

    # Cons / risks
    cons.append("Slightly increased breast cancer risk with combined HRT after ~5 years (transdermal lower risk than oral).")
    cons.append("DVT/clot risk — transdermal estrogen is lower risk than oral.")
    if not contras and not has_hot_flashes and not has_sleep_issues:
        cons.append("No clear vasomotor symptoms — cost/benefit less obvious without symptoms.")

    if contras:
        cons.append(f"Possible contraindication on file: {', '.join(contras)}. Discuss before starting.")

    # What's missing
    if not fsh:
        missing.append("FSH and Estradiol level (helps confirm menopausal status)")
    if not _latest_test(profile, "Lipid"):
        missing.append("Recent lipid panel (baseline before starting HRT)")
    missing.append("Confirmation of uterine status (if uterus present, progesterone is needed)")
    missing.append("Personal preference on patch vs oral vs gel/cream")
    missing.append("Baseline mammogram if not recent")

    questions = [
        "Given my symptoms and family history, do you recommend HRT and at what dose?",
        "Transdermal vs oral — which fits my risk profile?",
        "If I have a uterus, what progesterone option do you recommend (micronized, IUD, synthetic)?",
        "Should I include testosterone for libido or muscle mass?",
        "What's the recheck schedule (symptoms, labs, mammogram)?",
        "When would we revisit whether to continue?",
    ]

    return {
        "applicable": True,
        "age": age,
        "symptoms_present": [
            *(["hot_flashes"] if has_hot_flashes else []),
            *(["sleep_issues"] if has_sleep_issues else []),
            *(["brain_fog"] if has_brain_fog else []),
            *(["joint_pain"] if has_joint_pain else []),
        ],
        "contraindications_flagged": contras,
        "pros": pros,
        "cons": cons,
        "missing": missing,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Statin decision aid
# ---------------------------------------------------------------------------

def statin_decision(profile: dict[str, Any]) -> dict[str, Any]:
    age = calculate_age_from_dob(profile.get("date_of_birth", "")) or 0
    ldl_t = _latest_test(profile, "LDL")
    hdl_t = _latest_test(profile, "HDL")
    tot_t = _latest_test(profile, "Total Cholesterol")
    bp = None
    has_diabetes = bool(_has_condition(profile, ["diabetes", "type 2", "type 1"]))
    has_existing_cv = bool(_has_condition(profile, ["coronary artery", "stroke", "heart attack",
                                                    "myocardial infarction", "tia"]))
    family_cv = []
    for fh in profile.get("family_history", []):
        cond = str(fh.get("condition", "")).lower()
        if any(t in cond for t in ("heart attack", "myocardial", "stroke", "early cardiac")):
            family_cv.append(fh)

    pros = []
    cons = []
    missing = []

    try:
        ldl = float(ldl_t.get("value")) if ldl_t else None
    except (TypeError, ValueError):
        ldl = None

    if has_existing_cv:
        pros.append("Existing cardiovascular disease — secondary prevention statin is standard of care.")
    if has_diabetes and age >= 40:
        pros.append("Diabetes + age ≥40 is a strong indication for primary prevention statin in most guidelines.")
    if ldl is not None and ldl >= 190:
        pros.append(f"LDL ≥190 ({ldl} mg/dL) typically warrants statin regardless of other risk.")
    elif ldl is not None and ldl >= 160:
        pros.append(f"LDL {ldl} mg/dL is high — discuss statin vs intensive lifestyle.")
    if family_cv:
        pros.append(f"Family history of early cardiovascular disease ({len(family_cv)} relative(s)) raises personal risk.")

    cons.append("Statins can cause muscle aches in ~5–10% (often resolves with dose adjustment or switching agent).")
    cons.append("Small risk of new-onset diabetes (~1 in 200/year).")
    cons.append("Lifelong commitment; lifestyle alone may suffice if LDL is borderline and risk is low.")

    if ldl is None:
        missing.append("Recent LDL value")
    missing.append("Calculated 10-year ASCVD risk score (your clinician can run this)")
    missing.append("Coronary artery calcium (CAC) score — useful for borderline cases")
    missing.append("ApoB measurement — more direct atherogenic particle count than LDL")
    missing.append("Lp(a) — once-in-life test that informs lifetime risk")
    missing.append("Blood pressure history")

    questions = [
        "What is my calculated 10-year ASCVD risk?",
        "Should I get a CAC score to refine the decision?",
        "Is ApoB more useful than LDL for me?",
        "If I try lifestyle changes for 3–6 months first, what targets and timeline?",
        "Which statin and dose would you start with given my profile?",
    ]

    return {
        "ldl": ldl,
        "has_diabetes": has_diabetes,
        "has_existing_cv": has_existing_cv,
        "family_cv_count": len(family_cv),
        "pros": pros,
        "cons": cons,
        "missing": missing,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Screening intensity
# ---------------------------------------------------------------------------

def screening_intensity_decision(profile: dict[str, Any]) -> dict[str, Any]:
    age = calculate_age_from_dob(profile.get("date_of_birth", "")) or 0
    sex = str(profile.get("sex", "")).lower()
    fh = profile.get("family_history", []) or []
    breast_fh = [f for f in fh if "breast" in str(f.get("condition", "")).lower()]
    colon_fh = [f for f in fh if "colon" in str(f.get("condition", "")).lower()]

    notes: list[str] = []
    questions: list[str] = []

    if sex == "female":
        if breast_fh:
            youngest = min((float(f.get("age_at_diagnosis", 999)) for f in breast_fh), default=999)
            recommended_start = max(30, youngest - 10) if youngest < 999 else 35
            notes.append(f"Family breast cancer history → consider starting mammogram around age {recommended_start:.0f}.")
            if age >= recommended_start - 2:
                questions.append("Should I start (or shift to) annual mammograms given family history?")
                questions.append("Should I add breast MRI given family history?")
                questions.append("Is genetic testing (BRCA1/BRCA2, panel) worth it for me?")

    if colon_fh:
        youngest = min((float(f.get("age_at_diagnosis", 999)) for f in colon_fh), default=999)
        recommended_start = max(30, youngest - 10) if youngest < 999 else 40
        notes.append(f"Family colon cancer history → consider starting colonoscopy around age {recommended_start:.0f}.")
        if age >= recommended_start - 2:
            questions.append(f"Should I start colonoscopy at age {recommended_start:.0f} instead of 45?")
            questions.append("Is the cadence 5 or 10 years given my family history?")

    if not notes:
        notes.append("No high-risk family history of breast or colon cancer on file. Standard cadence applies (mammogram from 40–50 every 1–2y; colonoscopy from 45 every 10y).")

    return {
        "age": age,
        "sex": sex,
        "notes": notes,
        "questions": questions or [
            "What's the right screening cadence for me given my age and family history?",
            "Are there any imaging or genetic tests I should add?",
        ],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_decision_md(title: str, body_lines: list[str]) -> str:
    lines = [f"# Decision aid: {title}", "",
             f"_Generated {date.today().isoformat()}_", "",
             "**This is a structured conversation tool, not a recommendation.** "
             "Use it to organise the conversation with your clinician, not to make the decision yourself.", ""]
    lines.extend(body_lines)
    lines.append("")
    return "\n".join(lines) + "\n"


def _bullet_list(items: list[str]) -> list[str]:
    return [f"- {x}" for x in items] if items else ["- _(none on file)_"]


def write_hrt_decision(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    d = hrt_decision(profile)
    if not d.get("applicable"):
        text = render_decision_md("HRT", [d.get("reason", "Not applicable.")])
    else:
        body = []
        body.append("## Your situation")
        body.append("")
        body.append(f"- Age: {d['age']}")
        if d["symptoms_present"]:
            body.append(f"- Symptoms in recent check-ins: {', '.join(d['symptoms_present'])}")
        if d["contraindications_flagged"]:
            body.append(f"- ⚠ Possible contraindications: {', '.join(d['contraindications_flagged'])}")
        body.append("")
        body.append("## Reasons it could help")
        body.append("")
        body.extend(_bullet_list(d["pros"]))
        body.append("")
        body.append("## Things to weigh")
        body.append("")
        body.extend(_bullet_list(d["cons"]))
        body.append("")
        body.append("## What I'd want to know before deciding")
        body.append("")
        body.extend(_bullet_list(d["missing"]))
        body.append("")
        body.append("## Questions for the clinician")
        body.append("")
        body.extend(_bullet_list(d["questions"]))
        text = render_decision_md("HRT", body)
    path = decisions_dir(root, person_id) / "HRT.md"
    atomic_write_text(path, text)
    return path


def write_statin_decision(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    d = statin_decision(profile)
    body = []
    body.append("## Your situation")
    body.append("")
    body.append(f"- Latest LDL: {d['ldl']} mg/dL" if d["ldl"] else "- LDL: not on file")
    body.append(f"- Diabetes on record: {'yes' if d['has_diabetes'] else 'no'}")
    body.append(f"- Existing cardiovascular disease: {'yes' if d['has_existing_cv'] else 'no'}")
    body.append(f"- Family early-CV-event history: {d['family_cv_count']} relative(s)")
    body.append("")
    body.append("## Reasons a statin may be indicated")
    body.append("")
    body.extend(_bullet_list(d["pros"]))
    body.append("")
    body.append("## Things to weigh")
    body.append("")
    body.extend(_bullet_list(d["cons"]))
    body.append("")
    body.append("## What I'd want to know before deciding")
    body.append("")
    body.extend(_bullet_list(d["missing"]))
    body.append("")
    body.append("## Questions for the clinician")
    body.append("")
    body.extend(_bullet_list(d["questions"]))
    text = render_decision_md("Statin (primary prevention)", body)
    path = decisions_dir(root, person_id) / "STATIN.md"
    atomic_write_text(path, text)
    return path


def write_screening_decision(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    d = screening_intensity_decision(profile)
    body = []
    body.append("## Your situation")
    body.append("")
    body.append(f"- Age: {d['age']}")
    body.append(f"- Sex: {d['sex']}")
    body.append("")
    body.append("## Notes")
    body.append("")
    for n in d["notes"]:
        body.append(f"- {n}")
    body.append("")
    body.append("## Questions for the clinician")
    body.append("")
    body.extend(_bullet_list(d["questions"]))
    text = render_decision_md("Screening intensity", body)
    path = decisions_dir(root, person_id) / "SCREENING.md"
    atomic_write_text(path, text)
    return path
