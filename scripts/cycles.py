#!/usr/bin/env python3
"""Menstrual cycle tracker for Health Skill v1.7.

PRIVACY: Cycles data is considered highly sensitive. It MUST NOT appear in
exported clinician packets, redacted summaries, or caregiver dashboards unless
the user has explicitly opted in via `preferences.track_cycles = True` AND a
separate export consent for the specific destination.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import upsert_record, load_profile, save_profile, ensure_person, now_utc
except ImportError:
    from care_workspace import upsert_record, load_profile, save_profile, ensure_person, now_utc


PRIVACY_NOTE = (
    "Cycles data is private. Excluded by default from clinician packets, "
    "redacted summaries, and caregiver dashboards."
)

SYMPTOM_WORDS = {
    "cramps": "cramps",
    "cramping": "cramps",
    "headache": "headache",
    "migraine": "headache",
    "mood swings": "mood swings",
    "irritable": "mood swings",
    "bloating": "bloating",
    "bloated": "bloating",
    "fatigue": "fatigue",
    "tired": "fatigue",
    "back pain": "back pain",
    "breast tenderness": "breast tenderness",
    "nausea": "nausea",
    "acne": "acne",
}

FLOW_WORDS = {
    "heavy flow": "heavy",
    "heavy bleeding": "heavy",
    "heavy": "heavy",
    "medium flow": "medium",
    "medium": "medium",
    "moderate flow": "medium",
    "light flow": "light",
    "light": "light",
    "spotting": "spotting",
}


def _parse_date_phrase(text: str, today: date | None = None) -> str:
    """Parse date references like 'today', 'yesterday', '3 days ago'."""
    today = today or date.today()
    t = text.lower()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s+days?\s+ago", t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s+weeks?\s+ago", t)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    # ISO date inline
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)
    return today.isoformat()


def parse_cycle_event(text: str) -> dict[str, Any]:
    """Parse a natural-language cycle event."""
    t = (text or "").lower()
    result: dict[str, Any] = {
        "event_type": "",
        "date": _parse_date_phrase(text),
        "flow": "",
        "symptoms": [],
    }

    if re.search(r"\bperiod\s+(?:started|starting|begun|begin|began)\b", t) or \
       re.search(r"\bstarted\s+(?:my\s+)?period\b", t) or \
       (re.search(r"\bstarted\b", t) and "period" in t):
        result["event_type"] = "period_started"
    elif re.search(r"\bperiod\s+(?:ended|over|finished|stopped|done)\b", t) or \
         re.search(r"\bended\s+(?:my\s+)?period\b", t):
        result["event_type"] = "period_ended"
    elif "ovulation" in t or "ovulating" in t:
        result["event_type"] = "ovulation"
    else:
        result["event_type"] = "symptom_log"

    for phrase, flow in FLOW_WORDS.items():
        if phrase in t:
            result["flow"] = flow
            break

    symptoms: list[str] = []
    for phrase, sym in SYMPTOM_WORDS.items():
        if phrase in t and sym not in symptoms:
            symptoms.append(sym)
    if "ovulation pain" in t and "ovulation pain" not in symptoms:
        symptoms.append("ovulation pain")
    result["symptoms"] = symptoms

    return result


def log_cycle_event(root: Path, person_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Apply a cycle event to the profile's cycles section."""
    ensure_person(root, person_id)
    profile = load_profile(root, person_id)
    cycles = list(profile.get("cycles", []) or [])
    etype = event.get("event_type", "")
    evt_date = event.get("date") or date.today().isoformat()
    flow = event.get("flow") or ""
    symptoms = list(event.get("symptoms") or [])

    # Sort by start_date for stable "most recent" lookup
    cycles.sort(key=lambda c: c.get("start_date", ""))

    if etype == "period_started":
        new_cycle = {
            "start_date": evt_date,
            "end_date": "",
            "flow": flow,
            "symptoms": symptoms,
            "length_days": None,
        }
        cycles.append(new_cycle)
    elif etype == "period_ended":
        # Close most recent open cycle
        open_cycle = None
        for c in reversed(cycles):
            if not c.get("end_date"):
                open_cycle = c
                break
        if open_cycle is not None:
            open_cycle["end_date"] = evt_date
            try:
                sd = date.fromisoformat(open_cycle["start_date"])
                ed = date.fromisoformat(evt_date)
                open_cycle["length_days"] = (ed - sd).days + 1
            except Exception:
                pass
            if flow and not open_cycle.get("flow"):
                open_cycle["flow"] = flow
            for s in symptoms:
                if s not in open_cycle.get("symptoms", []):
                    open_cycle.setdefault("symptoms", []).append(s)
        else:
            # No open cycle; create a closed stub
            cycles.append({
                "start_date": evt_date,
                "end_date": evt_date,
                "flow": flow,
                "symptoms": symptoms,
                "length_days": 1,
            })
    else:
        # symptom_log or ovulation: append to current/most recent cycle
        if cycles:
            target = cycles[-1]
            for s in symptoms:
                if s not in target.get("symptoms", []):
                    target.setdefault("symptoms", []).append(s)
            if flow and not target.get("flow"):
                target["flow"] = flow
            if etype == "ovulation":
                target.setdefault("events", []).append({"type": "ovulation", "date": evt_date})
        else:
            cycles.append({
                "start_date": evt_date,
                "end_date": "",
                "flow": flow,
                "symptoms": symptoms,
                "length_days": None,
                "events": [{"type": etype, "date": evt_date}] if etype != "symptom_log" else [],
            })

    profile["cycles"] = cycles
    profile.setdefault("audit", {})["updated_at"] = now_utc()
    save_profile(root, person_id, profile)
    return event


def predict_next_period(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    """Predict next period start based on the last ~3 cycle start dates."""
    if not cycles:
        return {"predicted_start": "", "avg_cycle_length": 0, "confidence": "low"}
    sorted_cycles = sorted(
        [c for c in cycles if c.get("start_date")],
        key=lambda c: c["start_date"],
    )
    if len(sorted_cycles) < 2:
        return {"predicted_start": "", "avg_cycle_length": 0, "confidence": "low"}
    recent = sorted_cycles[-4:]  # use up to 3 intervals (4 cycles)
    diffs: list[int] = []
    for a, b in zip(recent, recent[1:]):
        try:
            da = date.fromisoformat(a["start_date"])
            db = date.fromisoformat(b["start_date"])
            diffs.append((db - da).days)
        except Exception:
            continue
    if not diffs:
        return {"predicted_start": "", "avg_cycle_length": 0, "confidence": "low"}
    avg = sum(diffs) / len(diffs)
    try:
        last_start = date.fromisoformat(sorted_cycles[-1]["start_date"])
        predicted = (last_start + timedelta(days=round(avg))).isoformat()
    except Exception:
        predicted = ""
    # Confidence based on variance and sample size
    if len(diffs) >= 3:
        spread = max(diffs) - min(diffs)
        confidence = "high" if spread <= 3 else ("medium" if spread <= 7 else "low")
    elif len(diffs) == 2:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "predicted_start": predicted,
        "avg_cycle_length": round(avg, 1),
        "confidence": confidence,
    }


def render_cycles_text(profile: dict[str, Any]) -> str:
    """Render CYCLES.md with recent cycles, prediction, and patterns."""
    prefs = profile.get("preferences", {}) or {}
    cycles = list(profile.get("cycles", []) or [])
    lines = ["# Cycles", "", f"> PRIVACY: {PRIVACY_NOTE}", ""]
    if not prefs.get("track_cycles"):
        lines.append("_Cycle tracking is not enabled in preferences._")
        lines.append("")
        return "\n".join(lines)
    if not cycles:
        lines.append("_No cycles recorded yet._")
        lines.append("")
        return "\n".join(lines)

    cycles_sorted = sorted(cycles, key=lambda c: c.get("start_date", ""), reverse=True)
    prediction = predict_next_period(cycles)

    lines.append("## Prediction")
    if prediction["predicted_start"]:
        lines.append(
            f"- Next period: **{prediction['predicted_start']}** "
            f"(avg cycle {prediction['avg_cycle_length']} days, confidence: {prediction['confidence']})"
        )
    else:
        lines.append("- Not enough data for a prediction yet.")
    lines.append("")

    lines.append("## Recent cycles")
    for c in cycles_sorted[:6]:
        start = c.get("start_date", "?")
        end = c.get("end_date") or "ongoing"
        length = c.get("length_days")
        flow = c.get("flow") or "-"
        syms = ", ".join(c.get("symptoms", []) or []) or "-"
        length_str = f"{length}d" if length else "-"
        lines.append(f"- {start} → {end} | length {length_str} | flow {flow} | symptoms: {syms}")
    lines.append("")

    # Patterns: most common symptoms
    sym_count: dict[str, int] = {}
    for c in cycles:
        for s in c.get("symptoms", []) or []:
            sym_count[s] = sym_count.get(s, 0) + 1
    if sym_count:
        top = sorted(sym_count.items(), key=lambda x: x[1], reverse=True)[:5]
        lines.append("## Patterns")
        for sym, n in top:
            lines.append(f"- {sym}: {n} cycle(s)")
        lines.append("")
    return "\n".join(lines)


def command_cycle_log(args: argparse.Namespace) -> int:
    root = Path(args.root)
    event = parse_cycle_event(args.text)
    if getattr(args, "date", ""):
        event["date"] = args.date
    log_cycle_event(root, args.person_id, event)
    print(f"Logged cycle event: {event}")
    return 0
