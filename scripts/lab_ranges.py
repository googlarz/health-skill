#!/usr/bin/env python3
"""Personalised lab reference ranges.

Standard reference ranges assume a healthy adult. This module adjusts ranges
based on the person's conditions, medications, age, and sex.

Usage:
    from lab_ranges import personalised_range, explain_range

    r = personalised_range("TSH", profile)
    # {"low": 0.5, "high": 2.5, "unit": "mIU/L", "note": "On levothyroxine: tighter range preferred"}
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Base reference ranges
# (low, high, unit, display_name)
# ---------------------------------------------------------------------------

BASE_RANGES: dict[str, dict[str, Any]] = {
    # Lipids
    "LDL":           {"low": 0,    "high": 130,  "unit": "mg/dL",    "optimal": 100},
    "HDL":           {"low": 40,   "high": 999,  "unit": "mg/dL",    "optimal": 60},   # higher = better
    "Triglycerides": {"low": 0,    "high": 150,  "unit": "mg/dL"},
    "Total Cholesterol": {"low": 0, "high": 200, "unit": "mg/dL"},
    "ApoB":          {"low": 0,    "high": 90,   "unit": "mg/dL"},

    # Glucose / metabolic
    "Glucose":       {"low": 70,   "high": 99,   "unit": "mg/dL"},
    "HbA1c":         {"low": 0,    "high": 5.6,  "unit": "%"},
    "Insulin":       {"low": 2,    "high": 20,   "unit": "uIU/mL"},
    "HOMA-IR":       {"low": 0,    "high": 1.9,  "unit": ""},

    # Thyroid
    "TSH":           {"low": 0.4,  "high": 4.0,  "unit": "mIU/L"},
    "Free T4":       {"low": 0.8,  "high": 1.8,  "unit": "ng/dL"},
    "Free T3":       {"low": 2.3,  "high": 4.2,  "unit": "pg/mL"},

    # Kidney
    "Creatinine":    {"low": 0.6,  "high": 1.2,  "unit": "mg/dL"},   # sex-adjusted below
    "eGFR":          {"low": 60,   "high": 999,  "unit": "mL/min/1.73m²"},
    "BUN":           {"low": 7,    "high": 20,   "unit": "mg/dL"},
    "Uric Acid":     {"low": 2.4,  "high": 7.0,  "unit": "mg/dL"},

    # Liver
    "ALT":           {"low": 7,    "high": 40,   "unit": "U/L"},
    "AST":           {"low": 10,   "high": 40,   "unit": "U/L"},
    "GGT":           {"low": 9,    "high": 48,   "unit": "U/L"},
    "ALP":           {"low": 44,   "high": 147,  "unit": "U/L"},
    "Bilirubin":     {"low": 0.2,  "high": 1.2,  "unit": "mg/dL"},
    "Albumin":       {"low": 3.5,  "high": 5.0,  "unit": "g/dL"},

    # Blood count
    "Hemoglobin":    {"low": 12.0, "high": 17.5, "unit": "g/dL"},    # sex-adjusted below
    "WBC":           {"low": 4.5,  "high": 11.0, "unit": "K/uL"},
    "Platelets":     {"low": 150,  "high": 400,  "unit": "K/uL"},
    "MCV":           {"low": 80,   "high": 100,  "unit": "fL"},

    # Inflammation
    "CRP":           {"low": 0,    "high": 1.0,  "unit": "mg/L"},    # hs-CRP optimal <1
    "ESR":           {"low": 0,    "high": 20,   "unit": "mm/hr"},
    "Ferritin":      {"low": 12,   "high": 150,  "unit": "ng/mL"},

    # Vitamins / minerals
    "Vitamin D":     {"low": 30,   "high": 100,  "unit": "ng/mL",    "optimal": 50},
    "Vitamin B12":   {"low": 200,  "high": 900,  "unit": "pg/mL"},
    "Folate":        {"low": 2.7,  "high": 17.0, "unit": "ng/mL"},
    "Iron":          {"low": 60,   "high": 170,  "unit": "ug/dL"},
    "TIBC":          {"low": 250,  "high": 370,  "unit": "ug/dL"},
    "Magnesium":     {"low": 1.7,  "high": 2.3,  "unit": "mg/dL"},
    "Zinc":          {"low": 60,   "high": 120,  "unit": "ug/dL"},

    # Hormones
    "Testosterone":  {"low": 300,  "high": 1000, "unit": "ng/dL"},   # sex-adjusted below
    "SHBG":          {"low": 10,   "high": 50,   "unit": "nmol/L"},
    "Estradiol":     {"low": 30,   "high": 400,  "unit": "pg/mL"},   # phase-dependent
    "FSH":           {"low": 1.5,  "high": 12.4, "unit": "mIU/mL"},
    "LH":            {"low": 1.7,  "high": 15.0, "unit": "mIU/mL"},
    "DHEA-S":        {"low": 35,   "high": 430,  "unit": "ug/dL"},
    "Cortisol":      {"low": 6,    "high": 23,   "unit": "ug/dL"},   # AM draw
    "Prolactin":     {"low": 2,    "high": 29,   "unit": "ng/mL"},
    "IGF-1":         {"low": 115,  "high": 307,  "unit": "ng/mL"},

    # Cardiac
    "hsCRP":         {"low": 0,    "high": 1.0,  "unit": "mg/L"},
    "Homocysteine":  {"low": 0,    "high": 10,   "unit": "umol/L"},
    "Lp(a)":         {"low": 0,    "high": 30,   "unit": "mg/dL"},
    "BNP":           {"low": 0,    "high": 100,  "unit": "pg/mL"},

    # Blood pressure (stored as systolic/diastolic string)
    "blood_pressure": {"low_sys": 90, "high_sys": 120, "low_dia": 60, "high_dia": 80, "unit": "mmHg"},
}


# ---------------------------------------------------------------------------
# Adjustments: (condition_keyword, marker, delta_low, delta_high, note)
# delta = None means "replace the value"
# ---------------------------------------------------------------------------

CONDITION_ADJUSTMENTS: list[dict[str, Any]] = [
    # Diabetes — tighter targets
    {
        "condition": "diabetes",
        "marker": "HbA1c",
        "new_high": 7.0,
        "note": "Diabetes: ADA target <7% on treatment (individualised — may be <8% for elderly or complex patients)",
    },
    {
        "condition": "diabetes",
        "marker": "LDL",
        "new_high": 100,
        "note": "Diabetes: LDL target <100 mg/dL (high cardiovascular risk category)",
    },
    {
        "condition": "diabetes",
        "marker": "Glucose",
        "new_high": 130,
        "note": "Diabetes: fasting glucose 80–130 mg/dL is ADA target range",
    },
    # Hypothyroidism on levothyroxine — tighter TSH
    {
        "condition": "hypothyroid",
        "marker": "TSH",
        "new_low": 0.5,
        "new_high": 2.5,
        "note": "On levothyroxine: most clinicians target TSH 0.5–2.5 mIU/L (tighter than population normal)",
    },
    # CKD — different creatinine context
    {
        "condition": "kidney disease",
        "marker": "eGFR",
        "new_low": 30,
        "note": "CKD: eGFR 30–60 = stage 3, <30 = stage 4. Monitor trend not just level.",
    },
    # Cardiovascular disease — more aggressive LDL
    {
        "condition": "heart disease",
        "marker": "LDL",
        "new_high": 70,
        "note": "Known cardiovascular disease: ACC/AHA target LDL <70 mg/dL",
    },
    {
        "condition": "heart attack",
        "marker": "LDL",
        "new_high": 70,
        "note": "Post-MI: ACC/AHA target LDL <70 mg/dL",
    },
    {
        "condition": "stroke",
        "marker": "LDL",
        "new_high": 70,
        "note": "Post-stroke: ACC/AHA target LDL <70 mg/dL",
    },
    # PCOS
    {
        "condition": "pcos",
        "marker": "Testosterone",
        "note": "PCOS: testosterone often elevated; interpret alongside free testosterone and SHBG",
    },
    # Menopause
    {
        "condition": "menopause",
        "marker": "FSH",
        "new_low": 25,
        "new_high": 135,
        "note": "Post-menopause: FSH typically >25–40 mIU/mL",
    },
    {
        "condition": "menopause",
        "marker": "Estradiol",
        "new_high": 30,
        "note": "Post-menopause (no HRT): estradiol typically <30 pg/mL",
    },
    # Pregnancy
    {
        "condition": "pregnant",
        "marker": "TSH",
        "new_high": 2.5,
        "note": "Pregnancy trimester 1: TSH target <2.5 mIU/L",
    },
    {
        "condition": "pregnant",
        "marker": "Hemoglobin",
        "new_low": 10.5,
        "note": "Pregnancy: anaemia defined as Hgb <10.5 g/dL (dilutional decrease is normal)",
    },
]

MEDICATION_ADJUSTMENTS: list[dict[str, Any]] = [
    {
        "medication": "levothyroxine",
        "marker": "TSH",
        "new_low": 0.5,
        "new_high": 2.5,
        "note": "On levothyroxine: target TSH 0.5–2.5 mIU/L",
    },
    {
        "medication": "metformin",
        "marker": "Vitamin B12",
        "new_low": 300,
        "note": "Metformin depletes B12 over time; target >300 pg/mL on metformin",
    },
    {
        "medication": "statin",
        "marker": "LDL",
        "new_high": 100,
        "note": "On statin therapy: LDL target typically <100 mg/dL",
    },
    {
        "medication": "biotin",
        "marker": "TSH",
        "note": "Biotin >5mg/day can falsely lower TSH on immunoassays — stop biotin 48h before thyroid labs",
    },
    {
        "medication": "biotin",
        "marker": "Free T4",
        "note": "Biotin interferes with T4 immunoassays — stop biotin 48h before thyroid labs",
    },
    {
        "medication": "warfarin",
        "marker": "INR",
        "new_low": 2.0,
        "new_high": 3.0,
        "note": "On warfarin: therapeutic INR 2.0–3.0 for most indications (2.5–3.5 for mechanical valves)",
    },
]

SEX_ADJUSTMENTS: dict[str, dict[str, dict[str, Any]]] = {
    "female": {
        "Hemoglobin":   {"new_low": 12.0, "new_high": 16.0,
                         "note": "Female reference range"},
        "Creatinine":   {"new_low": 0.5,  "new_high": 1.1,
                         "note": "Female reference range"},
        "Testosterone": {"new_low": 15,   "new_high": 70,   "unit": "ng/dL",
                         "note": "Female reference range (total testosterone)"},
        "Ferritin":     {"new_low": 12,   "new_high": 150,
                         "note": "Female reference range (premenopausal)"},
        "SHBG":         {"new_low": 17,   "new_high": 124,
                         "note": "Female reference range"},
        "HDL":          {"new_low": 50,   "note": "Female: HDL >50 preferred"},
    },
    "male": {
        "Hemoglobin":   {"new_low": 13.5, "new_high": 17.5,
                         "note": "Male reference range"},
        "Creatinine":   {"new_low": 0.7,  "new_high": 1.3,
                         "note": "Male reference range"},
        "Ferritin":     {"new_low": 24,   "new_high": 336,
                         "note": "Male reference range"},
        "SHBG":         {"new_low": 10,   "new_high": 57,
                         "note": "Male reference range"},
    },
}


def _normalise_name(name: str) -> str:
    return name.strip().lower()


def _marker_matches(marker: str, target: str) -> bool:
    return _normalise_name(marker) == _normalise_name(target)


def _condition_matches(profile_conditions: list[dict[str, Any]], keyword: str) -> bool:
    kw = keyword.lower()
    for c in profile_conditions:
        if kw in (c.get("name") or "").lower():
            return True
    return False


def _medication_matches(profile_meds: list[dict[str, Any]], keyword: str) -> bool:
    kw = keyword.lower()
    for m in profile_meds:
        name = (m.get("name") or "").lower()
        if kw in name or name in kw:
            return True
    return False


def personalised_range(
    marker: str, profile: dict[str, Any]
) -> dict[str, Any]:
    """Return a personalised reference range dict for the given marker.

    Keys: low, high, unit, notes (list of strings), optimal (optional)
    """
    base = BASE_RANGES.get(marker)
    if not base:
        # Try case-insensitive lookup
        for k, v in BASE_RANGES.items():
            if _marker_matches(k, marker):
                base = dict(v)
                marker = k
                break
    if not base:
        return {"low": None, "high": None, "unit": "", "notes": []}

    result = dict(base)
    notes: list[str] = []

    sex = (profile.get("sex") or "").lower()
    conditions = profile.get("conditions") or []
    medications = profile.get("medications") or []

    # Sex adjustments (applied before condition/medication overrides)
    if sex in SEX_ADJUSTMENTS:
        adj = SEX_ADJUSTMENTS[sex].get(marker)
        if adj:
            for k, v in adj.items():
                if k == "note":
                    notes.append(v)
                elif k == "new_low":
                    result["low"] = v
                elif k == "new_high":
                    result["high"] = v
                else:
                    result[k] = v

    # Condition adjustments
    for adj in CONDITION_ADJUSTMENTS:
        if not _marker_matches(adj["marker"], marker):
            continue
        if not _condition_matches(conditions, adj["condition"]):
            continue
        if "new_low" in adj:
            result["low"] = adj["new_low"]
        if "new_high" in adj:
            result["high"] = adj["new_high"]
        if "note" in adj:
            notes.append(adj["note"])

    # Medication adjustments
    for adj in MEDICATION_ADJUSTMENTS:
        if not _marker_matches(adj["marker"], marker):
            continue
        if not _medication_matches(medications, adj["medication"]):
            continue
        if "new_low" in adj:
            result["low"] = adj["new_low"]
        if "new_high" in adj:
            result["high"] = adj["new_high"]
        if "note" in adj:
            notes.append(adj["note"])

    result["notes"] = notes
    return result


def flag_lab_value(
    marker: str, value: float, profile: dict[str, Any]
) -> str:
    """Return 'high', 'low', 'optimal', or 'normal' for a lab value."""
    r = personalised_range(marker, profile)
    low = r.get("low")
    high = r.get("high")
    optimal = r.get("optimal")

    if low is not None and value < low:
        return "low"
    if high is not None and high < 999 and value > high:
        return "high"
    if optimal is not None:
        # HDL: higher is better, flag as optimal if above optimal
        if marker == "HDL" and value >= optimal:
            return "optimal"
        # Vitamin D
        if marker == "Vitamin D" and low is not None and high is not None:
            if low <= value <= optimal:
                return "normal"
            if value > optimal:
                return "optimal"
    return "normal"


def render_range_context(marker: str, value: float, profile: dict[str, Any]) -> str:
    """Return a plain-English sentence explaining how a value compares to personalised range."""
    r = personalised_range(marker, profile)
    flag = flag_lab_value(marker, value, profile)
    unit = r.get("unit", "")
    low = r.get("low")
    high = r.get("high")
    notes = r.get("notes", [])

    range_str = ""
    if low is not None and high is not None and high < 999:
        range_str = f"{low}–{high} {unit}".strip()
    elif low is not None:
        range_str = f">{low} {unit}".strip()
    elif high is not None and high < 999:
        range_str = f"<{high} {unit}".strip()

    flag_text = {"high": "above", "low": "below", "normal": "within", "optimal": "at optimal level for"}.get(flag, "within")
    line = f"{marker} {value} {unit} — {flag_text} your personalised range ({range_str})."
    if notes:
        line += " " + notes[0]
    return line.strip()
