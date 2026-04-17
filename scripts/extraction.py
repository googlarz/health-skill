#!/usr/bin/env python3
"""Document reading, extraction, and inbox processing for Health Skill."""

from __future__ import annotations

import calendar
import re
import shutil
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from PIL import Image
except ImportError:
    Image = None

# NOTE: keep both import blocks in sync
try:
    from .care_workspace import (
        add_note,
        archive_dir,
        document_already_ingested,
        ensure_person,
        file_content_hash,
        humanize_name,
        inbox_dir,
        interpret_against_range,
        list_inbox_files,
        load_review_queue,
        normalize_lab_flag,
        normalize_test_name,
        now_utc,
        save_review_queue,
        slugify,
        title_case_name,
        upsert_record,
        log_extraction_event,
    )
except ImportError:
    from care_workspace import (
        add_note,
        archive_dir,
        document_already_ingested,
        ensure_person,
        file_content_hash,
        humanize_name,
        inbox_dir,
        interpret_against_range,
        list_inbox_files,
        load_review_queue,
        normalize_lab_flag,
        normalize_test_name,
        now_utc,
        save_review_queue,
        slugify,
        title_case_name,
        upsert_record,
        log_extraction_event,
    )


def document_preview(document_path: Path, page_limit: int = 10) -> str:
    suffix = document_path.suffix.lower()
    raw_text, mode = read_document_text_with_mode(document_path, page_limit=page_limit)
    if not raw_text:
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"} and Image is not None:
            try:
                with Image.open(document_path) as image:
                    return (
                        f"Image stored ({image.width}x{image.height}). OCR is unavailable in this environment. "
                        "Manual review required."
                    )
            except Exception:
                pass
        if suffix == ".pdf":
            return "PDF stored but no extractable text was found. It may be scanned; OCR is unavailable here."
        return "Binary or unsupported document stored. Manual review required."

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    preview = " ".join(lines[:12])
    preview = re.sub(r"\s+", " ", preview).strip()
    if len(preview) > 500:
        preview = preview[:497] + "..."
    if mode in {"image_ocr", "pdf_ocr"}:
        preview = f"[OCR] {preview}"
    return preview or "Document ingested with no extractable text preview."


def run_apple_ocr(path: Path) -> str:
    swift_path = Path(__file__).with_name("apple_ocr.swift")
    if not swift_path.exists():
        return ""
    try:
        completed = subprocess.run(
            ["/usr/bin/swift", str(swift_path), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (completed.stdout or "").strip()


def infer_doc_type(source_path: Path) -> str:
    name = source_path.name.lower()
    if any(token in name for token in ("lab", "cbc", "lipid", "a1c", "blood")):
        return "lab"
    if any(token in name for token in ("discharge", "after-visit", "avs")):
        return "discharge"
    if any(token in name for token in ("med", "medication", "rx", "prescription")):
        return "medication-list"
    if any(token in name for token in ("imaging", "xray", "mri", "ct", "ultrasound")):
        return "imaging"
    if any(token in name for token in ("visit", "consult", "follow-up", "followup")):
        return "visit-note"
    if any(token in name for token in ("plan", "care-plan")):
        return "care-plan"
    return "document"


def is_in_inbox(root: Path, person_id: str, source_path: Path) -> bool:
    try:
        return source_path.resolve().is_relative_to(inbox_dir(root, person_id).resolve())
    except ValueError:
        return False


def supported_text_document(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".txt", ".json", ".pdf"}


def read_document_text_with_mode(path: Path, page_limit: int = 10) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace"), "text"
    if suffix == ".pdf":
        if pdfplumber is not None:
            try:
                with pdfplumber.open(path) as pdf:
                    text = "\n".join((page.extract_text() or "") for page in pdf.pages[:page_limit]).strip()
                if text:
                    return text, "pdf_text"
            except Exception:
                pass
        if PdfReader is not None:
            try:
                reader = PdfReader(str(path))
                text = "\n".join((page.extract_text() or "") for page in reader.pages[:page_limit]).strip()
                if text:
                    return text, "pdf_text"
            except Exception:
                pass
        ocr_text = run_apple_ocr(path)
        return ocr_text, "pdf_ocr" if ocr_text else "none"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        ocr_text = run_apple_ocr(path)
        return ocr_text, "image_ocr" if ocr_text else "none"
    return "", "none"


def read_document_text(path: Path, page_limit: int = 10) -> str:
    return read_document_text_with_mode(path, page_limit=page_limit)[0]




def extract_lab_candidates(raw_text: str, source_date: str) -> list[dict[str, Any]]:
    candidates = []
    # Pattern 1: standard space-separated lab lines (named groups)
    _LAB_PATTERN_1 = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ()/%+-]{1,40}?)\s+(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%/]+)"
        r"(?:\s*\(?\s*(?P<low>-?\d+(?:\.\d+)?)\s*-\s*(?P<high>-?\d+(?:\.\d+)?)\s*\)?)?"
        r"(?:\s+(?P<flag>[HLN]|high|low|normal|abnormal))?\s*$",
        flags=re.IGNORECASE,
    )
    # Pattern 2: tab-separated, < or > prefixed values, multi-word test names (named groups)
    _LAB_PATTERN_2 = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ()/%+-]{1,60}?)"  # test name (wider)
        r"(?:\t|  +)"  # tab or 2+ spaces separator
        r"(?P<value>[<>]?\s*-?\d+(?:\.\d+)?)\s*"  # value with optional < or >
        r"(?P<unit>[A-Za-z%/]+)"  # unit
        r"(?:\s*\(?\s*(?P<low>-?\d+(?:\.\d+)?)\s*-\s*(?P<high>-?\d+(?:\.\d+)?)\s*\)?)?"  # optional range
        r"(?:\s+(?P<flag>[HLN]|high|low|normal|abnormal))?\s*$",
        flags=re.IGNORECASE,
    )
    # Pattern 3: parenthetical ranges like "LDL 162 mg/dL (goal <100)" or "TSH 4.5 mIU/L (0.4-4.0)"
    _LAB_PATTERN_3 = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ()/%+-]{1,40}?)\s+"
        r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%/]+)\s*"
        r"\(\s*(?:goal\s*)?(?P<range_spec>[<>]?\s*-?\d+(?:\.\d+)?(?:\s*-\s*-?\d+(?:\.\d+)?)?)\s*\)\s*$",
        flags=re.IGNORECASE,
    )
    # Pattern 4: semicolon-delimited CSV export fields
    _LAB_PATTERN_4 = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ()/%+-]{1,40}?)\s*;\s*"
        r"(?P<value>-?\d+(?:\.\d+)?)\s*;\s*(?P<unit>[A-Za-z%/]+)"
        r"(?:\s*;\s*(?P<low>-?\d+(?:\.\d+)?)\s*-\s*(?P<high>-?\d+(?:\.\d+)?))?"
        r"(?:\s*;\s*(?P<flag>[HLN]|high|low|normal|abnormal))?\s*$",
        flags=re.IGNORECASE,
    )
    for line in raw_text.splitlines():
        stripped = line.strip()
        match = _LAB_PATTERN_1.match(stripped)
        if not match:
            match = _LAB_PATTERN_2.match(stripped)
        if not match:
            match = _LAB_PATTERN_4.match(stripped)
        if not match:
            # Try pattern 3 (parenthetical range)
            m3 = _LAB_PATTERN_3.match(stripped)
            if m3:
                g3 = m3.groupdict()
                range_spec = g3["range_spec"].strip()
                low3 = None
                high3 = None
                # Parse range_spec: could be "<100", ">50", "0.4-4.0"
                range_match = re.match(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", range_spec)
                if range_match:
                    low3 = range_match.group(1)
                    high3 = range_match.group(2)
                else:
                    lt_match = re.match(r"<\s*(-?\d+(?:\.\d+)?)", range_spec)
                    gt_match = re.match(r">\s*(-?\d+(?:\.\d+)?)", range_spec)
                    if lt_match:
                        high3 = lt_match.group(1)
                    elif gt_match:
                        low3 = gt_match.group(1)
                # Construct a fake groupdict compatible with the rest
                match = type("_M", (), {"groupdict": lambda self: {
                    "name": g3["name"], "value": g3["value"], "unit": g3["unit"],
                    "low": low3, "high": high3, "flag": None,
                }})()
        if not match:
            continue
        groups = match.groupdict()
        name = groups["name"]
        value = groups["value"]
        unit = groups["unit"]
        low = groups["low"]
        high = groups["high"]
        raw_flag = groups["flag"]
        if len(name.strip()) < 2:
            continue
        # Strip < or > prefix for numeric comparison but keep in stored value
        numeric_str = re.sub(r"[<>\s]", "", value)
        try:
            numeric_value = float(numeric_str)
        except ValueError:
            continue
        low_value = float(low) if low is not None else None
        high_value = float(high) if high is not None else None
        normalized_flag = (
            normalize_lab_flag(raw_flag) if raw_flag else interpret_against_range(numeric_value, low_value, high_value)
        )
        reference_range = ""
        if low is not None and high is not None:
            reference_range = f"{low}-{high} {unit}"
        candidates.append(
            {
                "section": "recent_tests",
                "candidate": {
                    "name": normalize_test_name(name),
                    "value": value.strip(),
                    "unit": unit,
                    "date": source_date,
                    "reference_range": reference_range,
                    "flag": normalized_flag,
                    "interpretation": normalized_flag,
                },
                "confidence": "high",
                "auto_apply": True,
                "rationale": "Structured lab-style line detected in source document.",
                "source_snippet": stripped,
            }
        )
    return candidates


def extract_qualitative_lab_candidates(raw_text: str, source_date: str) -> list[dict[str, Any]]:
    """Extract qualitative lab results like 'HIV Screen Negative'."""
    candidates = []
    qualitative_pattern = re.compile(
        r"^\s*([A-Za-z][A-Za-z0-9 ()-]{2,50}?)\s+"
        r"(positive|negative|reactive|non-?reactive|detected|not detected|normal|abnormal|equivocal|indeterminate)\s*$",
        flags=re.IGNORECASE,
    )
    for line in raw_text.splitlines():
        stripped = line.strip()
        match = qualitative_pattern.match(stripped)
        if not match:
            continue
        name, result = match.groups()
        if len(name.strip()) < 3:
            continue
        candidates.append(
            {
                "section": "recent_tests",
                "candidate": {
                    "name": normalize_test_name(name),
                    "value": result.strip(),
                    "unit": "",
                    "date": source_date,
                    "reference_range": "",
                    "flag": "qualitative",
                    "interpretation": result.strip().lower(),
                },
                "confidence": "high",
                "auto_apply": True,
                "rationale": "Qualitative lab result detected in source document.",
                "source_snippet": stripped,
            }
        )
    return candidates


def extract_medication_candidates(raw_text: str, doc_type: str) -> list[dict[str, Any]]:
    candidates = []
    lab_like_names = {"ldl", "hdl", "a1c", "hba1c", "tsh", "bun", "alt", "ast"}
    frequency_tokens = {
        "daily": "daily",
        "nightly": "nightly",
        "weekly": "weekly",
        "bid": "twice daily",
        "tid": "three times daily",
        "prn": "as needed",
        "as needed": "as needed",
        "qd": "daily",
        "qhs": "at bedtime",
        "q4h": "every 4 hours",
        "q6h": "every 6 hours",
        "q8h": "every 8 hours",
        "q12h": "every 12 hours",
        "once weekly": "once weekly",
        "twice weekly": "twice weekly",
        "every other day": "every other day",
        "at bedtime": "at bedtime",
        "every morning": "every morning",
        "every evening": "every evening",
        "every night": "every night",
        "mon/wed/fri": "MWF",
        "mwf": "MWF",
        "as directed": "as directed",
        "with meals": "with meals",
        "before bed": "at bedtime",
    }
    form_tokens = {
        "tablet", "capsule", "inhaler", "patch", "solution", "cream", "spray",
        "injection", "ointment", "drops", "suppository",
    }
    # Extended release suffixes to keep attached to name
    _er_suffixes = re.compile(r"\b(ER|XR|SR|CR)\b", re.IGNORECASE)

    for line in raw_text.splitlines():
        stripped = line.strip()
        # Pattern 1: space between dose number and unit (e.g. "Lisinopril 10 mg daily")
        match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9/-]*(?: (?:ER|XR|SR|CR|[A-Za-z0-9/-]+)){0,3})\s+"
            r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\b(.*)$",
            stripped,
            flags=re.IGNORECASE,
        )
        # Pattern 2: no space between dose number and unit (e.g. "Lisinopril 10mg daily")
        if not match:
            match = re.match(
                r"^\s*([A-Za-z][A-Za-z0-9/-]*(?: (?:ER|XR|SR|CR|[A-Za-z0-9/-]+)){0,3})\s+"
                r"(\d+(?:\.\d+)?)(mg|mcg|g|ml|units?)\b(.*)$",
                stripped,
                flags=re.IGNORECASE,
            )
        # Pattern 3: "take X daily" verb prefix (e.g. "Take Lisinopril 10 mg daily")
        if not match:
            match = re.match(
                r"^\s*(?:take|use|apply|inject)\s+"
                r"([A-Za-z][A-Za-z0-9/-]*(?: (?:ER|XR|SR|CR|[A-Za-z0-9/-]+)){0,3})\s+"
                r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\b(.*)$",
                stripped,
                flags=re.IGNORECASE,
            )
        if not match:
            continue
        name, amount, unit, remainder = match.groups()
        if "/" in remainder or name.strip().lower() in lab_like_names:
            continue
        dose = f"{amount} {unit}{remainder}".strip()
        lowered_remainder = remainder.lower()
        frequency = ""
        form = ""
        for token, normalized in frequency_tokens.items():
            if token in lowered_remainder:
                frequency = normalized
                break
        for token in form_tokens:
            if token in lowered_remainder:
                form = token
                break
        candidates.append(
            {
                "section": "medications",
                "candidate": {
                    "name": title_case_name(name.strip().lower()),
                    "dose": re.sub(r"\s+", " ", dose),
                    "form": form,
                    "frequency": frequency,
                    "status": "needs-confirmation",
                },
                "confidence": "high" if doc_type == "medication-list" else "medium",
                "auto_apply": doc_type == "medication-list",
                "rationale": "Medication-style line with dose detected in source document.",
                "source_snippet": stripped,
            }
        )
    return candidates


def _parse_relative_date(text: str) -> str | None:
    """Convert relative date phrases like 'in 3 months' to ISO date strings."""
    today = date.today()
    # Match "in N weeks/months/days/years"
    match = re.search(r"\bin\s+(\d+)\s+(day|week|month|year)s?\b", text, re.IGNORECASE)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "day":
            return (today + timedelta(days=amount)).isoformat()
        if unit == "week":
            return (today + timedelta(weeks=amount)).isoformat()
        if unit == "month":
            # Approximate: add months by manipulating month/year
            month = today.month - 1 + amount
            year = today.year + month // 12
            month = month % 12 + 1
            day = min(today.day, calendar.monthrange(year, month)[1])
            return date(year, month, day).isoformat()
        if unit == "year":
            try:
                return today.replace(year=today.year + amount).isoformat()
            except ValueError:
                return today.replace(year=today.year + amount, day=28).isoformat()
    return None


def _parse_absolute_date(text: str) -> str | None:
    """Try to extract an absolute date like 'by March 2026' or 'March 15, 2026'."""
    month_names = {
        name.lower(): idx
        for idx, name in enumerate(calendar.month_name)
        if name
    }
    month_abbr = {
        name.lower(): idx
        for idx, name in enumerate(calendar.month_abbr)
        if name
    }
    all_months = {**month_names, **month_abbr}

    # "by March 2026" or "March 2026"
    match = re.search(
        r"\b(?:by\s+)?([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text
    )
    if match:
        month_str, day_str, year_str = match.groups()
        month_num = all_months.get(month_str.lower())
        if month_num:
            try:
                return date(int(year_str), month_num, int(day_str)).isoformat()
            except ValueError:
                pass

    match = re.search(r"\b(?:by\s+)?([A-Za-z]+)\s+(\d{4})\b", text)
    if match:
        month_str, year_str = match.groups()
        month_num = all_months.get(month_str.lower())
        if month_num:
            return date(int(year_str), month_num, 1).isoformat()

    return None


_SPECIALIST_PATTERN = re.compile(
    r"(?:see|follow\s*up\s*with|return\s*to|refer(?:ral)?\s*to)\s+"
    r"(?:(?:Dr\.?\s*)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*))"
    r"(?:\s+in\s+(.+?))?(?:\s*[.;]|$)",
    re.IGNORECASE,
)

_KNOWN_SPECIALTIES = {
    "cardiologist", "cardiology", "endocrinologist", "endocrinology",
    "dermatologist", "dermatology", "neurologist", "neurology",
    "oncologist", "oncology", "rheumatologist", "rheumatology",
    "gastroenterologist", "gastroenterology", "pulmonologist", "pulmonology",
    "urologist", "urology", "nephrologist", "nephrology", "orthopedics",
    "ophthalmologist", "ophthalmology", "psychiatrist", "psychiatry",
    "allergist", "hematologist", "ent", "podiatrist",
}


def extract_follow_up_candidates(raw_text: str) -> list[dict[str, Any]]:
    candidates = []
    action_verbs = {"schedule", "recheck", "repeat", "return", "call if", "refer"}
    for line in raw_text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        is_follow_up = (
            "follow up" in lowered
            or "follow-up" in lowered
            or lowered.startswith("next:")
            or any(lowered.startswith(verb) or f" {verb}" in lowered for verb in action_verbs)
        )

        # Item 9: also match specialist referral patterns
        specialist_match = _SPECIALIST_PATTERN.search(stripped)
        specialist_name = ""
        if specialist_match:
            is_follow_up = True
            raw_specialist = (specialist_match.group(1) or "").strip()
            if raw_specialist.lower() in _KNOWN_SPECIALTIES:
                specialist_name = raw_specialist
            elif raw_specialist:
                specialist_name = raw_specialist

        # Also match "Return to [clinic/doctor]"
        return_match = re.search(
            r"(?:return\s+to|go\s+back\s+to)\s+([A-Za-z][A-Za-z0-9 .'-]{2,50})",
            stripped, re.IGNORECASE,
        )
        if return_match and not is_follow_up:
            is_follow_up = True
            if not specialist_name:
                specialist_name = return_match.group(1).strip()

        if not is_follow_up:
            continue

        # Try to extract a due date
        due_date = _parse_relative_date(lowered) or _parse_absolute_date(stripped)
        candidate: dict[str, Any] = {
            "task": stripped,
            "status": "needs-review",
        }
        if due_date:
            candidate["due_date"] = due_date
        if specialist_name:
            candidate["specialist"] = specialist_name
        candidates.append(
            {
                "section": "follow_up",
                "candidate": candidate,
                "confidence": "medium",
                "auto_apply": False,
                "rationale": "Follow-up style instruction detected in source document.",
                "source_snippet": stripped,
            }
        )
    return candidates[:5]


def classify_document_content(raw_text: str, filename_guess: str) -> str:
    """Refine document type using content keywords (Item 8)."""
    if not raw_text:
        return filename_guess

    lowered = raw_text.lower()

    # Lab keywords
    lab_keywords = {
        "reference range", "specimen", "ordered by", "result",
        "lab", "glucose", "hemoglobin", "cholesterol", "triglyceride",
        "creatinine", "potassium", "sodium", "platelet", "wbc", "rbc",
        "hematocrit", "bilirubin", "albumin",
    }
    lab_score = sum(1 for kw in lab_keywords if kw in lowered)

    # Medication keywords
    med_keywords = {"medication list", "prescription", "pharmacy", "refill", "dispense"}
    med_score = sum(1 for kw in med_keywords if kw in lowered)

    # Discharge keywords
    discharge_keywords = {"discharge", "discharge instructions", "after visit", "after-visit"}
    discharge_score = sum(1 for kw in discharge_keywords if kw in lowered)

    # Imaging keywords
    imaging_keywords = {"impression", "findings", "radiologist", "radiology", "imaging"}
    imaging_score = sum(1 for kw in imaging_keywords if kw in lowered)

    scores = {
        "lab": lab_score,
        "medication-list": med_score,
        "discharge": discharge_score,
        "imaging": imaging_score,
    }
    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best_type] >= 2:
        return best_type
    return filename_guess


_SEVERITY_ADJECTIVE_MAP: dict[str, str] = {
    "mild": "mild",
    "moderate": "moderate",
    "severe": "severe",
    "life-threatening": "life-threatening",
    "anaphylaxis": "life-threatening",
    "anaphylactic": "life-threatening",
}

_LIFE_THREATENING_REACTIONS = {"anaphylaxis", "anaphylactic shock", "angioedema"}


def _infer_severity(reaction_text: str) -> str:
    """Map reaction text to a severity_level enum value."""
    lowered = reaction_text.strip().lower()
    # Check for life-threatening keywords first
    for lt in _LIFE_THREATENING_REACTIONS:
        if lt in lowered:
            return "life-threatening"
    # Check for adjective prefix: "severe rash", "mild hives", etc.
    for adj, level in _SEVERITY_ADJECTIVE_MAP.items():
        if lowered.startswith(adj) or f" {adj} " in f" {lowered} ":
            return level
    return ""


def extract_allergy_candidates(raw_text: str) -> list[dict[str, Any]]:
    """Extract allergy mentions from document text (Item 9 + Item 8 severity)."""
    candidates = []

    # NKDA = No Known Drug Allergies — special case: note, not an allergy entry
    if re.search(r"\bNKDA\b", raw_text):
        candidates.append(
            {
                "section": "allergies",
                "candidate": {
                    "substance": "NKDA",
                    "reaction": "no known drug allergies",
                    "severity_level": "",
                    "reaction_type": "note",
                },
                "confidence": "high",
                "auto_apply": False,
                "rationale": "NKDA notation detected — this is a note, not an allergy entry.",
                "source_snippet": "NKDA",
            }
        )

    # Pattern for parenthetical severity: "Penicillin (anaphylaxis)"
    paren_pattern = re.compile(
        r"(?:allergic to|allergy:\s*|allergies:\s*|adverse reaction to)?\s*"
        r"([A-Za-z][A-Za-z0-9 /-]{1,60}?)\s*\(\s*([^)]+)\s*\)",
        re.IGNORECASE | re.MULTILINE,
    )

    # General allergy patterns
    allergy_patterns = [
        re.compile(
            r"(?:allergic to|allergy:\s*|allergies:\s*|adverse reaction to)\s+"
            r"([A-Za-z][A-Za-z0-9 ,/-]{1,80}?)(?:\s*[-\u2013(]\s*(.+?)[\s)]*)?$",
            re.IGNORECASE | re.MULTILINE,
        ),
    ]

    seen_substances: set[str] = set()

    # First pass: parenthetical severity pattern
    for match in paren_pattern.finditer(raw_text):
        substance = match.group(1).strip().rstrip(",;.")
        reaction = match.group(2).strip().rstrip(",;.)")
        if len(substance) < 2 or substance.lower() == "nkda":
            continue
        # Skip if substance looks like a lab name (number-heavy)
        if re.match(r"^\d", substance):
            continue
        severity = _infer_severity(reaction)
        sub_key = substance.lower()
        if sub_key in seen_substances:
            continue
        seen_substances.add(sub_key)
        candidates.append(
            {
                "section": "allergies",
                "candidate": {
                    "substance": substance,
                    "reaction": reaction,
                    "severity_level": severity,
                    "reaction_type": "drug" if reaction else "unknown",
                },
                "confidence": "medium",
                "auto_apply": False,
                "rationale": "Allergy with parenthetical reaction/severity detected.",
                "source_snippet": match.group(0).strip(),
            }
        )

    # Second pass: general allergy patterns
    for pattern in allergy_patterns:
        for match in pattern.finditer(raw_text):
            substance = match.group(1).strip().rstrip(",;.")
            reaction = (match.group(2) or "").strip().rstrip(",;.)")
            if len(substance) < 2:
                continue
            sub_key = substance.lower()
            if sub_key in seen_substances:
                continue
            seen_substances.add(sub_key)
            severity = _infer_severity(reaction) if reaction else ""
            candidates.append(
                {
                    "section": "allergies",
                    "candidate": {
                        "substance": substance,
                        "reaction": reaction,
                        "severity_level": severity,
                        "reaction_type": "drug" if reaction else "unknown",
                    },
                    "confidence": "medium",
                    "auto_apply": False,
                    "rationale": "Allergy mention detected in document.",
                    "source_snippet": match.group(0).strip(),
                }
            )
    return candidates


def extract_condition_candidates(raw_text: str) -> list[dict[str, Any]]:
    """Extract condition/diagnosis mentions from document text (Item 9)."""
    candidates = []

    # Look for section headers then capture lines underneath
    section_pattern = re.compile(
        r"(?:diagnosis|assessment|problem list|active problems)\s*[:\-]?\s*\n((?:.+\n?){1,20})",
        re.IGNORECASE,
    )
    # ICD-like code pattern: letter followed by digits, optionally dot + digits
    icd_pattern = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b")

    for section_match in section_pattern.finditer(raw_text):
        block = section_match.group(1)
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) < 3:
                continue
            # Stop at next section header
            if re.match(r"^[A-Z][a-z]+(\s+[A-Za-z]+){0,3}\s*:", stripped):
                break
            icd_match = icd_pattern.search(stripped)
            icd_code = icd_match.group(1) if icd_match else ""
            # Clean up line: remove bullets, numbering
            name = re.sub(r"^[\d.)\-*\u2022]+\s*", "", stripped)
            # Remove ICD code from name if present
            if icd_code:
                name = name.replace(icd_code, "").strip(" -,()")
            if len(name) < 3:
                continue
            candidate_data: dict[str, Any] = {
                "name": name,
                "status": "needs-confirmation",
            }
            if icd_code:
                candidate_data["icd_code"] = icd_code
            candidates.append(
                {
                    "section": "conditions",
                    "candidate": candidate_data,
                    "confidence": "medium",
                    "auto_apply": False,
                    "rationale": "Condition/diagnosis detected under assessment or problem list.",
                    "source_snippet": stripped,
                }
            )

    # Also look for inline "diagnosis: X" on a single line
    inline_pattern = re.compile(
        r"(?:diagnosis|dx)\s*[:\-]\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    )
    for match in inline_pattern.finditer(raw_text):
        name = match.group(1).strip().rstrip(",;.")
        if len(name) < 3:
            continue
        icd_match = icd_pattern.search(name)
        icd_code = icd_match.group(1) if icd_match else ""
        clean_name = name.replace(icd_code, "").strip(" -,()") if icd_code else name
        if len(clean_name) < 3:
            continue
        candidate_data = {
            "name": clean_name,
            "status": "needs-confirmation",
        }
        if icd_code:
            candidate_data["icd_code"] = icd_code
        candidates.append(
            {
                "section": "conditions",
                "candidate": candidate_data,
                "confidence": "medium",
                "auto_apply": False,
                "rationale": "Inline diagnosis mention detected in document.",
                "source_snippet": match.group(0).strip(),
            }
        )

    return candidates


def extract_candidates_from_document(
    path: Path,
    doc_type: str,
    source_date: str,
    page_limit: int = 10,
) -> list[dict[str, Any]]:
    raw_text, mode = read_document_text_with_mode(path, page_limit=page_limit)
    if not raw_text:
        return []

    candidates = []
    if doc_type in {"lab", "document"}:
        candidates.extend(extract_lab_candidates(raw_text, source_date))
        candidates.extend(extract_qualitative_lab_candidates(raw_text, source_date))
    candidates.extend(extract_medication_candidates(raw_text, doc_type))
    candidates.extend(extract_follow_up_candidates(raw_text))
    candidates.extend(extract_allergy_candidates(raw_text))
    candidates.extend(extract_condition_candidates(raw_text))
    if mode in {"image_ocr", "pdf_ocr"}:
        for item in candidates:
            item["auto_apply"] = False
            item["confidence"] = "medium" if item.get("confidence") == "high" else item.get("confidence", "medium")
            item["rationale"] = item.get("rationale", "") + " Extracted via OCR; confirm before trusting."
    return candidates


def add_review_items(
    root: Path,
    person_id: str,
    items: list[dict[str, Any]],
    source_title: str,
    source_date: str,
) -> list[dict[str, Any]]:
    queue = load_review_queue(root, person_id)
    created = []
    for item in items:
        review_id = f"review-{uuid.uuid4().hex[:12]}"
        review_item = {
            "id": review_id,
            "status": "open",
            "applied": item.get("auto_apply", False),
            "section": item["section"],
            "candidate": item["candidate"],
            "confidence": item.get("confidence", "medium"),
            "tier": review_tier_for_item(item),
            "rationale": item.get("rationale", ""),
            "source_snippet": item.get("source_snippet", ""),
            "source_title": source_title,
            "source_date": source_date,
            "detected_at": now_utc(),
        }
        queue.append(review_item)
        created.append(review_item)
    save_review_queue(root, person_id, queue)
    return created


def process_extracted_candidates(
    root: Path,
    person_id: str,
    source_title: str,
    source_date: str,
    extracted_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    created = add_review_items(root, person_id, extracted_items, source_title, source_date)
    for item, review_item in zip(extracted_items, created):
        # Log every extraction for accuracy tracking
        log_extraction_event(
            root, person_id,
            event_type="auto_applied" if item.get("auto_apply") else "extracted",
            section=item["section"],
            candidate=item["candidate"],
            confidence=item.get("confidence", ""),
            tier=review_item.get("tier", ""),
            source_title=source_title,
            source_snippet=item.get("source_snippet", ""),
            review_id=review_item["id"],
        )
        if item.get("auto_apply"):
            upsert_record(
                root,
                person_id,
                item["section"],
                item["candidate"],
                source_type="document-extraction",
                source_label=source_title,
                source_date=source_date,
            )
    return created


def review_tier_for_item(item: dict[str, Any]) -> str:
    if item.get("auto_apply"):
        return "safe_to_auto_apply"
    confidence = item.get("confidence", "medium")
    if confidence == "high":
        return "needs_quick_confirmation"
    return "do_not_trust_without_human_review"


def ingest_document(
    root: Path,
    person_id: str,
    source_path: Path,
    doc_type: str,
    title: str = "",
    source_date: str = "",
    page_limit: int = 10,
) -> tuple[Path, Path]:
    ensure_person(root, person_id)

    # Item 10: content hash dedup -- compute once, reuse everywhere
    content_hash = file_content_hash(source_path)
    if document_already_ingested(root, person_id, source_path, precomputed_hash=content_hash):
        print(f"[dedup] Skipping '{source_path.name}' -- content hash {content_hash[:12]}... already ingested.")
        # Return existing archived path from the profile, or source as fallback
        existing_archive = archive_dir(root, person_id) / source_path.name
        return existing_archive, existing_archive
    normalized_source_date = source_date or date.today().isoformat()
    safe_title = title or humanize_name(source_path.stem)
    destination_name = f"{date.today().isoformat()}-{slugify(safe_title)}{source_path.suffix.lower()}"
    destination_path = archive_dir(root, person_id) / destination_name
    if is_in_inbox(root, person_id, source_path):
        shutil.move(str(source_path), str(destination_path))
        ingest_mode = "moved_from_inbox"
    else:
        shutil.copy2(source_path, destination_path)
        ingest_mode = "copied"

    preview = document_preview(destination_path, page_limit=page_limit)
    extracted_items = extract_candidates_from_document(
        destination_path,
        doc_type,
        normalized_source_date,
        page_limit=page_limit,
    )
    processed_reviews = process_extracted_candidates(
        root,
        person_id,
        safe_title,
        normalized_source_date,
        extracted_items,
    )
    record = {
        "title": safe_title,
        "doc_type": doc_type,
        "source_date": normalized_source_date,
        "original_path": source_path.name,
        "archived_path": str(destination_path),
        "ingest_mode": ingest_mode,
        "content_hash": content_hash,
        "review_required": True,
        "review_queue_items": [item["id"] for item in processed_reviews],
        "preview_excerpt": preview,
    }
    upsert_record(
        root,
        person_id,
        "documents",
        record,
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    upsert_record(
        root,
        person_id,
        "encounters",
        {
            "date": normalized_source_date,
            "kind": doc_type,
            "title": safe_title,
            "summary": preview,
        },
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    note_path = add_note(
        root,
        person_id,
        f"Document ingest: {safe_title}",
        f"Document type: {doc_type}\n\nPreview:\n{preview}\n\n"
        f"Extraction candidates created: {len(processed_reviews)}\n\n"
        "Manual review required before relying on extracted facts.",
        source_type="document",
        source_label=safe_title,
        source_date=normalized_source_date,
    )
    return destination_path, note_path


def process_inbox(
    root: Path,
    person_id: str,
    dry_run: bool = False,
    page_limit: int = 10,
) -> list[tuple[Path, Path]]:
    ensure_person(root, person_id)
    files = list_inbox_files(root, person_id)
    if dry_run:
        for source_path in files:
            filename_guess = infer_doc_type(source_path)
            raw_text = read_document_text(source_path, page_limit=page_limit)
            doc_type = classify_document_content(raw_text, filename_guess)
            print(f"[dry-run] {source_path.name} -> type={doc_type}")
        return []
    processed = []
    for source_path in files:
        filename_guess = infer_doc_type(source_path)
        raw_text = read_document_text(source_path, page_limit=page_limit)
        doc_type = classify_document_content(raw_text, filename_guess)
        archived_path, note_path = ingest_document(
            root,
            person_id,
            source_path,
            doc_type,
            title=humanize_name(source_path.stem),
            source_date="",
            page_limit=page_limit,
        )
        processed.append((archived_path, note_path))
    return processed
