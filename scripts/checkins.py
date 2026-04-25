#!/usr/bin/env python3
"""Daily check-in natural-language parser for Health Skill v1.7."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import upsert_record, load_profile
except ImportError:
    from care_workspace import upsert_record, load_profile


MOOD_ADJECTIVES = {
    "awful": 2, "terrible": 2, "horrible": 2,
    "bad": 3, "low": 3, "down": 3, "sad": 3,
    "tired": 4, "meh": 4, "stressed": 4,
    "ok": 5, "okay": 5, "fine": 5, "alright": 5,
    "decent": 6,
    "good": 7, "happy": 7, "positive": 7,
    "great": 9, "excellent": 9, "amazing": 9, "wonderful": 9,
}

PAIN_WORDS = {
    "knee": "knee",
    "back": "back",
    "lower back": "back",
    "head": "head",
    "headache": "head",
    "migraine": "head",
    "neck": "neck",
    "shoulder": "shoulder",
    "shoulders": "shoulder",
    "stomach": "stomach",
    "belly": "stomach",
    "tummy": "stomach",
}

SLEEP_QUALITY_WORDS = {
    "good sleep": "good",
    "slept well": "good",
    "great sleep": "good",
    "poor sleep": "poor",
    "bad sleep": "poor",
    "slept badly": "poor",
    "restless": "poor",
    "ok sleep": "ok",
}

APPETITE_WORDS = {
    "no appetite": "low",
    "low appetite": "low",
    "not hungry": "low",
    "high appetite": "high",
    "hungry": "high",
    "normal appetite": "normal",
}


def _num(match_str: str) -> float:
    return float(match_str)


def parse_checkin(text: str) -> dict[str, Any]:
    """Parse a natural-language daily check-in string into a structured dict."""
    if not text:
        return {}
    original = text
    t = text.lower()
    consumed_spans: list[tuple[int, int]] = []
    result: dict[str, Any] = {}

    # Shorthand: ":7" (mood), "s7" or "s7.5" (sleep hours), "e7" (energy),
    # "p3" (pain), "w72" (weight kg). Allows quickest possible logging.

    # ":N" mood shortcut anywhere in the input
    m_colon = re.search(r"(?:^|\s):(\d+(?:\.\d+)?)\b", t)
    if m_colon:
        v = float(m_colon.group(1))
        if 0 <= v <= 10 and "mood" not in result:
            result["mood"] = int(v) if v.is_integer() else v
            consumed_spans.append((m_colon.start(), m_colon.end()))

    for m in re.finditer(r"(?:^|\s)([msepw])(\d+(?:\.\d+)?)(?=\s|$|[,;])", t):
        prefix = m.group(1)
        val = float(m.group(2))
        if prefix == "m" and 0 <= val <= 10 and "mood" not in result:
            result["mood"] = int(val) if val.is_integer() else val
            consumed_spans.append((m.start(), m.end()))
        elif prefix == "s" and 0 <= val <= 14 and "sleep_hours" not in result:
            result["sleep_hours"] = val
            consumed_spans.append((m.start(), m.end()))
        elif prefix == "e" and 0 <= val <= 10 and "energy" not in result:
            result["energy"] = int(val) if val.is_integer() else val
            consumed_spans.append((m.start(), m.end()))
        elif prefix == "p" and 0 <= val <= 10 and "pain_severity" not in result:
            result["pain_severity"] = int(val) if val.is_integer() else val
            consumed_spans.append((m.start(), m.end()))
        elif prefix == "w" and 30 <= val <= 300 and "weight_kg" not in result:
            result["weight_kg"] = val
            consumed_spans.append((m.start(), m.end()))

    def consume(m: re.Match) -> None:
        consumed_spans.append((m.start(), m.end()))

    # Mood: "mood 7" or "mood: 7"
    m = re.search(r"\bmood\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?", t)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 10:
            result["mood"] = int(val) if val.is_integer() else val
            consume(m)

    # Energy: "energy 8"
    m = re.search(r"\benergy\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?", t)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 10:
            result["energy"] = int(val) if val.is_integer() else val
            consume(m)

    # Stress: "stress 6" or "stressed 7"
    m = re.search(r"\bstress(?:ed)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?", t)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 10:
            result["stress"] = int(val) if val.is_integer() else val
            consume(m)
    elif "stressed" in t or "stress" in t:
        result["stress"] = 7

    # Sleep hours: "slept 6 hours", "6 hours sleep", "sleep: 7h"
    m = re.search(r"\bslept\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", t)
    if not m:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s+(?:of\s+)?sleep\b", t)
    if not m:
        m = re.search(r"\bsleep\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)?\b", t)
    if m:
        result["sleep_hours"] = float(m.group(1))
        consume(m)

    # Sleep quality
    for phrase, q in SLEEP_QUALITY_WORDS.items():
        if phrase in t:
            result["sleep_quality"] = q
            break

    # Weight: "weight 72kg", "72 kg", "160 lbs"
    m = re.search(r"\bweight\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(kg|kilos?|lb|lbs|pounds?)?\b", t)
    if not m:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|kilos?|lb|lbs|pounds?)\b", t)
    if m:
        weight = float(m.group(1))
        unit = (m.group(2) or "kg").lower()
        if unit.startswith("lb") or unit.startswith("pound"):
            weight = round(weight * 0.453592, 2)
        result["weight_kg"] = weight
        consume(m)

    # Pain: "knee hurts 3/10", "back pain", "headache"
    pain_locs: list[str] = []
    for word, loc in PAIN_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            if loc not in pain_locs:
                pain_locs.append(loc)
    # Pain severity: "N/10" or "hurts N" or "pain N"
    m = re.search(r"(?:hurts?|pain)\s*(\d+(?:\.\d+)?)\s*/\s*10", t)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10\s*(?:pain|hurt)", t)
    if not m:
        m = re.search(r"\bpain\s*[:=]?\s*(\d+(?:\.\d+)?)\b", t)
    if m:
        sev = float(m.group(1))
        if 0 <= sev <= 10:
            result["pain_severity"] = int(sev) if sev.is_integer() else sev
            consume(m)
    if pain_locs:
        result["pain_locations"] = pain_locs

    # Appetite
    for phrase, a in APPETITE_WORDS.items():
        if phrase in t:
            result["appetite"] = a
            break

    # Mood inference from adjectives if not set
    if "mood" not in result:
        for adj, score in MOOD_ADJECTIVES.items():
            if re.search(rf"\b{re.escape(adj)}\b", t):
                result["mood"] = score
                break

    # Build notes: strip consumed spans
    consumed_spans.sort()
    remaining = []
    cursor = 0
    for start, end in consumed_spans:
        if start > cursor:
            remaining.append(original[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(original):
        remaining.append(original[cursor:])
    notes = " ".join(" ".join(remaining).split()).strip(" ,;.")
    if notes and len(notes) > 2:
        result["notes"] = notes

    return result


def save_checkin(root: Path, person_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
    """Save a parsed check-in to the daily_checkins section."""
    candidate = dict(parsed)
    candidate.setdefault("date", date.today().isoformat())
    upsert_record(
        root,
        person_id,
        "daily_checkins",
        candidate,
        source_type="user",
        source_label="daily-checkin",
        source_date=candidate["date"],
    )
    return candidate


def render_checkins_text(profile: dict[str, Any]) -> str:
    """Render recent daily check-ins as markdown."""
    checkins = list(profile.get("daily_checkins", []) or [])
    if not checkins:
        return "# Daily Check-ins\n\n_No check-ins recorded yet._\n"
    checkins.sort(key=lambda c: c.get("date", ""), reverse=True)
    recent = checkins[:14]

    lines = ["# Daily Check-ins", ""]
    # Mini-trends
    moods = [c.get("mood") for c in recent if isinstance(c.get("mood"), (int, float))]
    sleeps = [c.get("sleep_hours") for c in recent if isinstance(c.get("sleep_hours"), (int, float))]
    energies = [c.get("energy") for c in recent if isinstance(c.get("energy"), (int, float))]
    lines.append("## Recent trends (last 14 entries)")
    if moods:
        lines.append(f"- Mood avg: {sum(moods)/len(moods):.1f} (n={len(moods)})")
    if sleeps:
        lines.append(f"- Sleep avg: {sum(sleeps)/len(sleeps):.1f}h (n={len(sleeps)})")
    if energies:
        lines.append(f"- Energy avg: {sum(energies)/len(energies):.1f} (n={len(energies)})")
    lines.append("")
    lines.append("## Entries")
    for c in recent:
        parts = [f"**{c.get('date','?')}**"]
        if c.get("mood") is not None:
            parts.append(f"mood {c['mood']}")
        if c.get("sleep_hours") is not None:
            parts.append(f"sleep {c['sleep_hours']}h")
        if c.get("energy") is not None:
            parts.append(f"energy {c['energy']}")
        if c.get("stress") is not None:
            parts.append(f"stress {c['stress']}")
        if c.get("pain_locations"):
            locs = ",".join(c["pain_locations"])
            sev = c.get("pain_severity")
            parts.append(f"pain {locs}" + (f" {sev}/10" if sev is not None else ""))
        if c.get("weight_kg") is not None:
            parts.append(f"weight {c['weight_kg']}kg")
        line = " | ".join(parts)
        if c.get("notes"):
            line += f" -- {c['notes']}"
        lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def command_daily_checkin(args: argparse.Namespace) -> int:
    root = Path(args.root)
    parsed = parse_checkin(args.text)
    if getattr(args, "date", ""):
        parsed["date"] = args.date
    saved = save_checkin(root, args.person_id, parsed)
    print(f"Saved check-in for {saved['date']}: {saved}")
    return 0
