#!/usr/bin/env python3
"""Men's health companion for Health Skill.

Covers:
- Testosterone and Low-T context (equivalent depth to HRT in menopause.py)
- PSA screening and trend interpretation
- Prostate health and BPH context
- Male-specific cardiovascular risk framing
- Erectile dysfunction as cardiovascular sentinel
- Testicular health awareness
- Male fertility markers
- Age-appropriate preventive care schedule

This module is the counterpart to menopause.py for male-specific health depth.
"""

from __future__ import annotations

from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Testosterone: phenotype stages
# ---------------------------------------------------------------------------

TESTOSTERONE_STAGES = {
    "normal": {
        "description": "Testosterone within the typical male range.",
        "total_t_nmol_l": (10.4, 34.7),   # ~300–1000 ng/dL
        "free_t_pmol_l": (174, 729),
        "note": "Symptoms still matter even with 'normal' numbers — the lower end of normal can be symptomatic.",
    },
    "low_normal": {
        "description": "Borderline — symptoms may appear despite technically normal lab values.",
        "total_t_nmol_l": (8.0, 10.4),
        "note": "Consider full panel: SHBG, albumin, LH, FSH, prolactin before deciding on TRT.",
    },
    "hypogonadism": {
        "description": "Testosterone below the normal male range. Warrants investigation.",
        "total_t_nmol_l": (0, 8.0),
        "note": "Primary (testicular) vs secondary (pituitary) origin changes treatment. LH/FSH clarifies.",
    },
    "elevated": {
        "description": "Testosterone above the typical range — usually exogenous (TRT, steroids).",
        "total_t_nmol_l": (34.7, None),
        "note": "Elevated T suppresses LH/FSH and sperm production. Hematocrit monitoring important.",
    },
}

TESTOSTERONE_SYMPTOMS = {
    "fatigue": {
        "aliases": ["tired", "exhausted", "low energy", "no motivation"],
        "low_t_association": "strong",
        "non_t_causes": ["thyroid", "sleep apnea", "depression", "anaemia", "diabetes"],
    },
    "low_libido": {
        "aliases": ["no sex drive", "low sex drive", "decreased libido"],
        "low_t_association": "strong",
        "non_t_causes": ["relationship factors", "depression", "SSRI side effect", "high prolactin"],
    },
    "erectile_dysfunction": {
        "aliases": ["ED", "erection problems", "impotence"],
        "low_t_association": "moderate",
        "non_t_causes": ["cardiovascular disease", "diabetes", "hypertension", "anxiety", "medications"],
        "cardiovascular_flag": True,
        "note": "ED is an independent cardiovascular risk factor. Warrants lipids + BP evaluation.",
    },
    "mood_changes": {
        "aliases": ["irritable", "depressed", "brain fog", "poor concentration"],
        "low_t_association": "moderate",
        "non_t_causes": ["depression", "sleep disorder", "thyroid", "burnout"],
    },
    "muscle_loss": {
        "aliases": ["losing muscle", "muscle weakness", "sarcopenia", "less strength"],
        "low_t_association": "strong",
        "non_t_causes": ["inactivity", "protein deficiency", "ageing", "glucocorticoids"],
    },
    "body_fat_increase": {
        "aliases": ["gaining belly fat", "visceral fat", "weight gain"],
        "low_t_association": "moderate",
        "non_t_causes": ["diet", "sedentary", "hypothyroidism", "insulin resistance"],
    },
    "sleep_disturbance": {
        "aliases": ["can't sleep", "poor sleep", "insomnia"],
        "low_t_association": "moderate",
        "non_t_causes": ["sleep apnea", "stress", "shift work"],
        "note": "Sleep apnea both lowers T and is associated with low T — bidirectional.",
    },
    "hot_flushes": {
        "aliases": ["hot flashes", "sweating", "night sweats"],
        "low_t_association": "moderate",
        "note": "Less common in men than women, but occurs with low/dropping T.",
    },
}

# TRT options context (informational only — patient education)
TRT_OPTIONS = {
    "topical_gel": {
        "description": "Daily gel applied to skin. Maintains stable levels.",
        "pros": ["stable levels", "easy to adjust dose", "no injections"],
        "cons": ["transfer risk to partners/children", "daily application"],
        "monitoring": ["total T at 3–6 months", "hematocrit", "PSA if ≥40", "lipids"],
    },
    "injections": {
        "description": "IM injection every 1–4 weeks (or more frequent short-esters).",
        "pros": ["cost-effective", "no transfer risk", "definite absorption"],
        "cons": ["peaks and troughs", "injection discomfort", "more frequent monitoring"],
        "monitoring": ["trough T before next dose", "hematocrit", "PSA", "lipids"],
    },
    "pellets": {
        "description": "Subcutaneous pellets implanted every 3–6 months.",
        "pros": ["consistent levels", "infrequent dosing"],
        "cons": ["minor procedure", "cannot adjust dose once inserted"],
        "monitoring": ["T mid-cycle", "hematocrit", "PSA"],
    },
    "patches": {
        "description": "Daily transdermal patch.",
        "pros": ["steady state", "no transfer risk"],
        "cons": ["skin irritation", "visible"],
        "monitoring": ["total T", "hematocrit", "PSA"],
    },
}

TRT_CONTRAINDICATIONS = [
    "prostate cancer",
    "breast cancer",
    "polycythaemia",
    "untreated obstructive sleep apnea",
    "desire for fertility (active) — TRT suppresses sperm production",
    "severe lower urinary tract symptoms (relative)",
    "haematocrit > 54%",
]


# ---------------------------------------------------------------------------
# PSA interpretation
# ---------------------------------------------------------------------------

PSA_AGE_THRESHOLDS = {
    # (lower_age, upper_age): upper_normal_ng/ml
    (40, 49): 2.5,
    (50, 59): 3.5,
    (60, 69): 4.5,
    (70, 79): 6.5,
}

PSA_VELOCITY_CONCERN = 0.75  # ng/mL/year — above this warrants urologist referral

PROSTATE_FLAGS = {
    "psa_elevated": "PSA above age-adjusted upper limit",
    "psa_rising": f"PSA rising > {PSA_VELOCITY_CONCERN} ng/mL/year",
    "psa_density_high": "PSA density > 0.15 (if prostate volume known)",
    "free_psa_low": "Free/total PSA ratio < 25% increases cancer probability",
}


def interpret_psa(psa_value: float, age: int, prior_psa: float | None = None,
                  prior_psa_years_ago: float | None = None) -> dict[str, Any]:
    """Return structured PSA interpretation with flags."""
    result: dict[str, Any] = {
        "value": psa_value,
        "age": age,
        "flags": [],
        "recommendation": "",
    }

    # Age-adjusted threshold
    upper_limit = 4.0  # default if age out of range
    for (low_age, high_age), limit in PSA_AGE_THRESHOLDS.items():
        if low_age <= age <= high_age:
            upper_limit = limit
            break

    result["age_adjusted_upper"] = upper_limit

    if psa_value > upper_limit:
        result["flags"].append("elevated_for_age")

    # PSA velocity
    if prior_psa is not None and prior_psa_years_ago and prior_psa_years_ago > 0:
        velocity = (psa_value - prior_psa) / prior_psa_years_ago
        result["psa_velocity"] = round(velocity, 2)
        if velocity > PSA_VELOCITY_CONCERN:
            result["flags"].append("rising_velocity")

    # Recommendation
    if "elevated_for_age" in result["flags"] or "rising_velocity" in result["flags"]:
        result["recommendation"] = (
            "Discuss with your GP or urologist. A rising PSA or elevated PSA for your age "
            "warrants further evaluation — this does not confirm cancer but requires follow-up."
        )
    elif psa_value < 1.0:
        result["recommendation"] = "Low PSA — routine monitoring per your doctor's schedule."
    else:
        result["recommendation"] = "PSA within normal range for your age. Continue routine monitoring."

    return result


# ---------------------------------------------------------------------------
# Male preventive care schedule
# ---------------------------------------------------------------------------

MALE_PREVENTIVE_SCHEDULE = {
    "testicular_self_exam": {
        "frequency": "monthly",
        "age_start": 15,
        "age_end": 45,
        "note": "Peak incidence of testicular cancer in 15–35 age group. Monthly self-exam.",
        "what_to_check": "Painless lump, change in size, heaviness, dull ache.",
    },
    "blood_pressure": {
        "frequency": "annual",
        "age_start": 18,
        "note": "Hypertension often silent. Key cardiovascular risk factor.",
    },
    "lipid_panel": {
        "frequency": "every_5_years",
        "frequency_high_risk": "annual",
        "age_start": 35,
        "note": "Start at 25 if family history of early CVD, obesity, or diabetes.",
    },
    "fasting_glucose_hba1c": {
        "frequency": "every_3_years",
        "age_start": 40,
        "note": "Start earlier with obesity, family history, or symptoms.",
    },
    "psa_screening": {
        "frequency": "annual",
        "age_start": 50,
        "age_start_high_risk": 40,
        "note": "Shared decision with doctor. Black men and those with first-degree relatives with prostate cancer: start at 40–45.",
    },
    "colorectal_screening": {
        "frequency": "every_10_years",  # colonoscopy
        "age_start": 45,
        "note": "FIT test annually as alternative. Earlier with family history.",
    },
    "skin_check": {
        "frequency": "annual",
        "age_start": 40,
        "note": "Men over 50 are at higher melanoma risk than women of same age.",
    },
    "eye_exam": {
        "frequency": "every_2_years",
        "age_start": 40,
        "note": "Glaucoma risk increases with age.",
    },
    "hearing_test": {
        "frequency": "every_10_years",
        "age_start": 50,
        "note": "Occupational and recreational noise exposure accelerates loss.",
    },
    "abdominal_aortic_aneurysm": {
        "frequency": "once",
        "age_start": 65,
        "age_end": 75,
        "condition": "ever_smoked",
        "note": "One-time ultrasound for men 65–75 who have ever smoked.",
    },
    "testosterone_check": {
        "frequency": "as_needed",
        "note": "No universal screening. Check if symptomatic (fatigue, low libido, muscle loss, mood changes).",
    },
    "mental_health_screen": {
        "frequency": "annual",
        "note": "Men are less likely to present with depression; higher suicide risk. PHQ-2 at annual visit.",
    },
}


# ---------------------------------------------------------------------------
# Male cardiovascular risk framing
# ---------------------------------------------------------------------------

MALE_CV_RISK_FACTORS = {
    "age_over_45": {
        "description": "Men ≥45 have significantly higher CVD risk than younger men.",
        "action": "Annual BP check. Lipids every 5 years minimum.",
    },
    "family_history_early_cvd": {
        "description": "First-degree male relative with MI/stroke before 55, female before 65.",
        "action": "Start lipid screening at 25. Consider calcium score at 40+.",
    },
    "erectile_dysfunction": {
        "description": "ED is a vascular sentinel — often appears 3–5 years before cardiac events.",
        "action": "Treat as cardiovascular risk equivalent. Assess BP, lipids, glucose.",
        "urgency": "Do not ignore ED as 'just' a sexual issue.",
    },
    "central_obesity": {
        "description": "Waist circumference >102 cm (40 in) increases metabolic and CVD risk.",
        "action": "Weight management, fasting glucose, lipid panel.",
    },
    "smoking": {
        "description": "Single strongest modifiable risk factor for CVD and multiple cancers.",
        "action": "Cessation support. Combination therapy (varenicline + NRT) most effective.",
    },
    "sleep_apnea": {
        "description": "Untreated OSA raises BP, increases arrhythmia and CVD risk.",
        "action": "STOP-BANG score if snoring/witnessed apnoea/daytime sleepiness.",
    },
}


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------

def build_mens_health_report(profile: dict[str, Any]) -> str:
    """Generate a comprehensive men's health status report."""
    lines: list[str] = []
    lines.append("# Men's Health Report")
    lines.append("")

    age = _estimate_age(profile)
    sex = profile.get("sex", "").lower()
    if sex and sex not in ("male", "m", "man"):
        lines.append("*This report is designed for male physiology. Profile sex may not match.*\n")

    # --- Testosterone section ---
    lines.append("## Testosterone & Hormonal Health")
    t_findings = _testosterone_findings(profile)
    lines.append(t_findings)
    lines.append("")

    # --- PSA section ---
    if age and age >= 40:
        lines.append("## PSA & Prostate Health")
        psa_text = _psa_section(profile, age)
        lines.append(psa_text)
        lines.append("")

    # --- Cardiovascular risk ---
    lines.append("## Cardiovascular Risk Factors")
    cv_text = _cv_risk_section(profile)
    lines.append(cv_text)
    lines.append("")

    # --- Preventive care gaps ---
    lines.append("## Preventive Care for Men")
    prev_text = _preventive_gaps(profile, age or 40)
    lines.append(prev_text)
    lines.append("")

    # --- Mental health note ---
    lines.append("## Mental Health")
    lines.append(
        "Men are statistically less likely to seek help for depression and anxiety. "
        "Symptoms often present as irritability, anger, overwork, or substance use rather than sadness.\n"
        "If you've been feeling flat, disconnected, or more irritable than usual — that counts.\n"
        "Reach out to your GP or a counsellor. You don't have to be 'in crisis' to get support."
    )
    lines.append("")

    lines.append("---")
    lines.append("*This report is for awareness and conversation-starting. Not a diagnosis.*")
    return "\n".join(lines)


def score_testosterone_symptoms(profile: dict[str, Any]) -> dict[str, Any]:
    """Score low-T symptom burden from recent check-ins and profile notes."""
    symptoms_found: list[str] = []
    checkins = profile.get("daily_checkins", [])[-14:]  # last 14 days

    if checkins:
        avg_energy = sum(c.get("energy", 5) for c in checkins) / len(checkins)
        avg_mood = sum(c.get("mood", 5) for c in checkins) / len(checkins)
        if avg_energy < 4.5:
            symptoms_found.append("fatigue")
        if avg_mood < 4.5:
            symptoms_found.append("mood_changes")

    # Check note keywords
    for note in profile.get("notes", []):
        text = (note.get("text", "") if isinstance(note, dict) else str(note)).lower()
        for symptom, data in TESTOSTERONE_SYMPTOMS.items():
            for alias in data.get("aliases", []):
                if alias in text and symptom not in symptoms_found:
                    symptoms_found.append(symptom)

    score = len(symptoms_found)
    if score == 0:
        interpretation = "No significant low-T symptom burden detected."
        recommend = "Routine monitoring."
    elif score <= 2:
        interpretation = "Mild symptom burden. Could be low-T but many other causes possible."
        recommend = "Rule out thyroid, anaemia, sleep apnea, depression first."
    elif score <= 4:
        interpretation = "Moderate symptom burden consistent with low testosterone."
        recommend = "Request total T, free T, SHBG, LH, FSH, prolactin from your GP."
    else:
        interpretation = "High symptom burden. Multiple low-T indicators."
        recommend = "Discuss with GP or endocrinologist. Full hormonal panel warranted."

    return {
        "symptoms_found": symptoms_found,
        "score": score,
        "interpretation": interpretation,
        "recommendation": recommend,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_age(profile: dict[str, Any]) -> int | None:
    dob = profile.get("date_of_birth") or profile.get("dob")
    if dob:
        try:
            born = date.fromisoformat(dob)
            return (date.today() - born).days // 365
        except ValueError:
            pass
    return None


def _testosterone_findings(profile: dict[str, Any]) -> str:
    lines: list[str] = []
    symptom_result = score_testosterone_symptoms(profile)

    labs = {lr["marker"].lower(): lr for lr in profile.get("lab_results", [])}
    total_t = labs.get("total testosterone") or labs.get("testosterone, total") or labs.get("testosterone")

    if total_t:
        value = float(total_t.get("value", 0))
        unit = total_t.get("unit", "")
        lines.append(f"**Most recent total testosterone:** {value} {unit} ({total_t.get('date', '')})")
        # Simple nmol/L classification
        if "ng/dl" in unit.lower():
            value_nmol = value * 0.0347
        else:
            value_nmol = value
        for stage, data in TESTOSTERONE_STAGES.items():
            low, high = data["total_t_nmol_l"]
            if high is None:
                if value_nmol >= low:
                    lines.append(f"**Stage:** {stage.replace('_', ' ').title()}")
                    lines.append(f"*{data['note']}*")
                    break
            elif low <= value_nmol < high:
                lines.append(f"**Stage:** {stage.replace('_', ' ').title()}")
                lines.append(f"*{data['note']}*")
                break
    else:
        lines.append("No testosterone lab results found in your profile.")

    lines.append("")
    lines.append(f"**Symptom burden:** {symptom_result['interpretation']}")
    if symptom_result["symptoms_found"]:
        lines.append(f"Symptoms flagged: {', '.join(symptom_result['symptoms_found'])}")
    lines.append(f"**Recommendation:** {symptom_result['recommendation']}")

    return "\n".join(lines)


def _psa_section(profile: dict[str, Any], age: int) -> str:
    lines: list[str] = []
    labs = profile.get("lab_results", [])
    psa_labs = sorted(
        [lr for lr in labs if "psa" in lr.get("marker", "").lower()],
        key=lambda x: x.get("date", ""),
    )

    if not psa_labs:
        if age >= 50:
            lines.append("No PSA results found. Annual PSA discussion recommended for men ≥50.")
        elif age >= 40:
            lines.append("No PSA results found. Consider early baseline if family history of prostate cancer.")
        else:
            lines.append("PSA screening typically starts at 50 (or 40–45 with risk factors).")
        return "\n".join(lines)

    latest = psa_labs[-1]
    psa_val = float(latest.get("value", 0))
    prior_psa = float(psa_labs[-2]["value"]) if len(psa_labs) >= 2 else None

    # Estimate years between tests
    prior_years = None
    if prior_psa is not None and len(psa_labs) >= 2:
        try:
            d1 = date.fromisoformat(psa_labs[-2]["date"])
            d2 = date.fromisoformat(latest["date"])
            prior_years = (d2 - d1).days / 365.25
        except (ValueError, KeyError):
            pass

    interp = interpret_psa(psa_val, age, prior_psa, prior_years)

    lines.append(f"**Latest PSA:** {psa_val} ng/mL ({latest.get('date', '')})")
    lines.append(f"**Age-adjusted upper limit ({age} years):** {interp['age_adjusted_upper']} ng/mL")

    if "psa_velocity" in interp:
        lines.append(f"**PSA velocity:** {interp['psa_velocity']} ng/mL/year")

    if interp["flags"]:
        lines.append(f"⚠️ Flags: {', '.join(interp['flags'])}")

    lines.append(f"\n{interp['recommendation']}")

    return "\n".join(lines)


def _cv_risk_section(profile: dict[str, Any]) -> str:
    lines: list[str] = []
    conditions = [c["name"].lower() for c in profile.get("conditions", [])]
    notes_text = " ".join(
        (n.get("text", "") if isinstance(n, dict) else str(n)).lower()
        for n in profile.get("notes", [])
    )

    found_risks: list[str] = []

    age = _estimate_age(profile)
    if age and age >= 45:
        found_risks.append("age_over_45")

    if any("erectile" in c or " ed " in c or "impotence" in c for c in conditions) or \
       "erectile" in notes_text or "impotence" in notes_text:
        found_risks.append("erectile_dysfunction")

    if any("smok" in c for c in conditions) or "smok" in notes_text:
        found_risks.append("smoking")

    if any("sleep apnea" in c or "osa" in c for c in conditions):
        found_risks.append("sleep_apnea")

    if any("family history" in c and ("heart" in c or "cardio" in c or "mi" in c) for c in conditions) or \
       ("family history" in notes_text and ("heart" in notes_text or "cardiac" in notes_text)):
        found_risks.append("family_history_early_cvd")

    if not found_risks:
        lines.append("No specific cardiovascular risk flags detected from your profile.")
        lines.append("Keep up with annual BP and 5-yearly lipids.")
    else:
        for risk in found_risks:
            data = MALE_CV_RISK_FACTORS.get(risk, {})
            lines.append(f"**{risk.replace('_', ' ').title()}**")
            lines.append(data.get("description", ""))
            lines.append(f"→ {data.get('action', '')}")
            if data.get("urgency"):
                lines.append(f"⚠️ {data['urgency']}")
            lines.append("")

    return "\n".join(lines)


def _preventive_gaps(profile: dict[str, Any], age: int) -> str:
    lines: list[str] = []
    completed = {
        item.get("name", "").lower()
        for item in profile.get("preventive_care", [])
        if not item.get("overdue", False)
    }

    for screen_key, data in MALE_PREVENTIVE_SCHEDULE.items():
        age_start = data.get("age_start", 0)
        age_end = data.get("age_end", 999)
        if not (age_start <= age <= age_end):
            continue

        name = screen_key.replace("_", " ").title()
        freq = data.get("frequency", "")
        note = data.get("note", "")
        in_profile = any(screen_key in k for k in completed)

        status = "✓" if in_profile else "○"
        lines.append(f"{status} **{name}** ({freq}) — {note}")

    if not lines:
        lines.append("No age-appropriate male preventive items identified.")

    return "\n".join(lines)
