#!/usr/bin/env python3
"""FHIR R4 JSON import.

Patient portals (Epic MyChart, Cerner, Apple Health Records) export health
records in FHIR R4 JSON format. This module extracts:

- Conditions (diagnoses)
- Medications (active)
- Observations (lab results, vitals)
- Allergies
- Immunisations

Supports both a single FHIR Bundle and a directory of individual FHIR resources.

Usage:
    from fhir_import import import_fhir_bundle
    counts = import_fhir_bundle(root, person_id, path_to_json)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        load_profile,
        record_vital,
        record_weight,
        save_profile,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        load_profile,
        record_vital,
        record_weight,
        save_profile,
        workspace_lock,
    )


# FHIR Observation codes → internal metric names
LOINC_TO_METRIC: dict[str, tuple[str, str]] = {
    # Lipids
    "2093-3":  ("LDL", "mg/dL"),
    "18262-6": ("LDL", "mg/dL"),
    "2085-9":  ("HDL", "mg/dL"),
    "2089-1":  ("LDL", "mg/dL"),
    "2571-8":  ("Triglycerides", "mg/dL"),
    "2093-3":  ("Total Cholesterol", "mg/dL"),
    # Glucose
    "2339-0":  ("Glucose", "mg/dL"),
    "4548-4":  ("HbA1c", "%"),
    "17856-6": ("HbA1c", "%"),
    # Thyroid
    "3016-3":  ("TSH", "mIU/L"),
    "3051-0":  ("Free T3", "pg/mL"),
    "3054-4":  ("Free T4", "ng/dL"),
    # Kidney
    "2160-0":  ("Creatinine", "mg/dL"),
    "33914-3": ("eGFR", "mL/min/1.73m²"),
    "3094-0":  ("BUN", "mg/dL"),
    # Liver
    "1742-6":  ("ALT", "U/L"),
    "1920-8":  ("AST", "U/L"),
    "2324-2":  ("GGT", "U/L"),
    # Blood count
    "718-7":   ("Hemoglobin", "g/dL"),
    "6690-2":  ("WBC", "K/uL"),
    "777-3":   ("Platelets", "K/uL"),
    # Vitamins
    "1989-3":  ("Vitamin D", "ng/mL"),
    "2132-9":  ("Vitamin B12", "pg/mL"),
    # Inflammation
    "1988-5":  ("CRP", "mg/L"),
    "30522-7": ("hsCRP", "mg/L"),
    # Hormones
    "2986-8":  ("Testosterone", "ng/dL"),
    "2243-4":  ("FSH", "mIU/mL"),
    "10334-1": ("LH", "mIU/mL"),
    "2243-4":  ("Estradiol", "pg/mL"),
    # Vitals (observations)
    "8867-4":  ("heart_rate", "bpm"),
    "8480-6":  ("blood_pressure_systolic", "mmHg"),
    "8462-4":  ("blood_pressure_diastolic", "mmHg"),
    "29463-7": ("weight", "kg"),
    "8302-2":  ("height", "cm"),
    "39156-5": ("BMI", "kg/m²"),
    "59408-5": ("spo2", "%"),
    "8310-5":  ("body_temperature", "°C"),
}


def _parse_fhir_date(s: str) -> str:
    """Normalise FHIR date/dateTime to YYYY-MM-DD."""
    if not s:
        return ""
    return s[:10]


def _extract_value_quantity(obs: dict[str, Any]) -> tuple[float | None, str]:
    vq = obs.get("valueQuantity") or {}
    val = vq.get("value")
    unit = vq.get("unit") or vq.get("code") or ""
    if val is not None:
        return float(val), unit
    # valueString
    vs = obs.get("valueString")
    if vs:
        try:
            return float(vs), ""
        except ValueError:
            pass
    return None, unit


def _find_loinc_code(coding_list: list[dict[str, Any]]) -> str | None:
    for c in coding_list:
        if c.get("system", "").endswith("loinc.org"):
            return c.get("code")
    return None


def _process_bundle(bundle: dict[str, Any], root: Path, person_id: str) -> dict[str, int]:
    entries = bundle.get("entry") or []
    resources = [e.get("resource") for e in entries if e.get("resource")]
    return _process_resources(resources, root, person_id)


def _process_resources(
    resources: list[dict[str, Any]], root: Path, person_id: str
) -> dict[str, int]:
    counts: dict[str, int] = {}

    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)

        for r in resources:
            rtype = r.get("resourceType", "")

            if rtype == "Condition":
                counts["conditions"] = counts.get("conditions", 0) + _merge_condition(r, profile)

            elif rtype == "MedicationRequest" or rtype == "MedicationStatement":
                counts["medications"] = counts.get("medications", 0) + _merge_medication(r, profile)

            elif rtype == "AllergyIntolerance":
                counts["allergies"] = counts.get("allergies", 0) + _merge_allergy(r, profile)

            elif rtype == "Immunization":
                counts["immunisations"] = counts.get("immunisations", 0) + _merge_immunisation(r, profile)

            elif rtype == "Observation":
                added = _merge_observation(r, root, person_id, profile)
                for k, v in added.items():
                    counts[k] = counts.get(k, 0) + v

        save_profile(root, person_id, profile)

    return counts


def _merge_condition(r: dict, profile: dict) -> int:
    coding = (r.get("code") or {}).get("coding") or []
    text = (r.get("code") or {}).get("text") or ""
    name = text or (coding[0].get("display") if coding else "") or ""
    if not name:
        return 0

    status = (r.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "")
    if status in ("inactive", "resolved", "remission"):
        return 0

    onset = _parse_fhir_date(
        r.get("onsetDateTime") or r.get("onsetPeriod", {}).get("start") or ""
    )

    existing = profile.setdefault("conditions", [])
    for c in existing:
        if (c.get("name") or "").lower() == name.lower():
            return 0  # already present

    existing.append({"name": name, "diagnosed_date": onset, "source": "fhir"})
    return 1


def _merge_medication(r: dict, profile: dict) -> int:
    # MedicationRequest
    med_ref = r.get("medicationCodeableConcept") or r.get("medication") or {}
    coding = med_ref.get("coding") or []
    text = med_ref.get("text") or ""
    name = text or (coding[0].get("display") if coding else "") or ""
    if not name:
        return 0

    status = r.get("status", "")
    if status in ("stopped", "cancelled", "entered-in-error", "draft"):
        return 0

    dose_instructions = r.get("dosageInstruction") or []
    dose = ""
    if dose_instructions:
        d = dose_instructions[0]
        dq = (d.get("doseAndRate") or [{}])[0].get("doseQuantity") or {}
        val = dq.get("value")
        unit = dq.get("unit") or ""
        if val:
            dose = f"{val}{unit}"

    existing = profile.setdefault("medications", [])
    for m in existing:
        if (m.get("name") or "").lower() == name.lower():
            return 0

    existing.append({"name": name, "dose": dose, "source": "fhir"})
    return 1


def _merge_allergy(r: dict, profile: dict) -> int:
    coding = (r.get("code") or {}).get("coding") or []
    text = (r.get("code") or {}).get("text") or ""
    name = text or (coding[0].get("display") if coding else "") or ""
    if not name:
        return 0

    reaction_list = r.get("reaction") or []
    reaction = ""
    if reaction_list:
        manifestations = reaction_list[0].get("manifestation") or [{}]
        reaction = (manifestations[0].get("text") or
                    (manifestations[0].get("coding") or [{}])[0].get("display") or "")

    existing = profile.setdefault("allergies", [])
    for a in existing:
        if (a.get("name") or "").lower() == name.lower():
            return 0

    existing.append({"name": name, "reaction": reaction, "source": "fhir"})
    return 1


def _merge_immunisation(r: dict, profile: dict) -> int:
    coding = (r.get("vaccineCode") or {}).get("coding") or []
    text = (r.get("vaccineCode") or {}).get("text") or ""
    name = text or (coding[0].get("display") if coding else "") or ""
    if not name:
        return 0

    date_given = _parse_fhir_date(r.get("occurrenceDateTime") or "")
    existing = profile.setdefault("immunisations", [])
    for i in existing:
        if (i.get("name") or "").lower() == name.lower() and i.get("date") == date_given:
            return 0

    existing.append({"name": name, "date": date_given, "source": "fhir"})
    return 1


def _merge_observation(
    r: dict, root: Path, person_id: str, profile: dict
) -> dict[str, int]:
    counts: dict[str, int] = {}
    coding = (r.get("code") or {}).get("coding") or []
    obs_date = _parse_fhir_date(
        r.get("effectiveDateTime") or r.get("effectivePeriod", {}).get("start") or ""
    )
    if not obs_date:
        return counts

    value, unit = _extract_value_quantity(r)
    if value is None:
        return counts

    loinc = _find_loinc_code(coding)
    if loinc and loinc in LOINC_TO_METRIC:
        metric_name, default_unit = LOINC_TO_METRIC[loinc]
        u = unit or default_unit

        if metric_name == "weight":
            kg = value * 0.453592 if u.lower() in ("lbs", "lb", "[lb_av]") else value
            record_weight(root, person_id, obs_date, kg, "kg", "FHIR")
            counts["weight"] = 1
        elif metric_name in ("blood_pressure_systolic", "blood_pressure_diastolic"):
            # Store as vital; caller must pair them
            record_vital(root, person_id, obs_date, metric_name, str(value), "mmHg", "FHIR")
            counts["vitals"] = counts.get("vitals", 0) + 1
        elif metric_name in ("heart_rate", "spo2", "body_temperature", "BMI", "height"):
            record_vital(root, person_id, obs_date, metric_name, str(value), u, "FHIR")
            counts["vitals"] = counts.get("vitals", 0) + 1
        else:
            # Lab result
            display = (r.get("code") or {}).get("text") or metric_name
            _merge_lab_result(profile, display, value, u, obs_date)
            counts["labs"] = counts.get("labs", 0) + 1

    return counts


def _merge_lab_result(profile: dict, name: str, value: float, unit: str, date_str: str) -> None:
    tests = profile.setdefault("recent_tests", [])
    for t in tests:
        if (t.get("name") or "").lower() == name.lower() and t.get("date") == date_str:
            return
    tests.append({"name": name, "value": value, "unit": unit, "date": date_str, "source": "fhir"})


def import_fhir_file(root: Path, person_id: str, fhir_path: Path) -> dict[str, int]:
    """Import a FHIR R4 JSON file (Bundle or single resource). Returns counts."""
    if not fhir_path.exists():
        raise FileNotFoundError(fhir_path)

    try:
        data = json.loads(fhir_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Cannot parse {fhir_path.name}: {e}") from e

    rtype = data.get("resourceType", "")

    if rtype == "Bundle":
        return _process_bundle(data, root, person_id)

    # Single resource
    return _process_resources([data], root, person_id)


def is_fhir_file(path: Path) -> bool:
    """Quick check: does this JSON file look like a FHIR resource?"""
    if path.suffix.lower() != ".json":
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore")[:2000])
        rtype = data.get("resourceType", "")
        return rtype in (
            "Bundle", "Patient", "Condition", "Observation",
            "MedicationRequest", "MedicationStatement",
            "AllergyIntolerance", "Immunization",
        )
    except Exception:
        return False
