#!/usr/bin/env python3
"""Generate visit-specific clinician handoffs."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .care_workspace import (
        exports_dir,
        atomic_write_text,
        load_conflicts,
        load_profile,
        notes_dir,
        person_dir,
    )
    from .rendering import render_record
except ImportError:  # pragma: no cover
    from care_workspace import (
        exports_dir,
        atomic_write_text,
        load_conflicts,
        load_profile,
        notes_dir,
        person_dir,
    )
    from rendering import render_record


VISIT_HINTS = {
    "pcp": "Focus on longitudinal context, trends, and follow-up items.",
    "urgent-care": "Focus on the current issue, immediate red flags, and what changed recently.",
    "specialist": "Focus on the referral question, relevant prior workup, and targeted next questions.",
    "telehealth": "Focus on concise remote triage details and what can be assessed without an exam.",
}


def recent_notes(root: Path, person_id: str, limit: int) -> list[Path]:
    directory = notes_dir(root, person_id)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"), reverse=True)[:limit]


def suggested_questions(profile: dict, visit_type: str) -> list[str]:
    questions = []
    follow_up = profile.get("follow_up", [])
    unresolved = profile.get("unresolved_questions", [])
    if visit_type == "specialist":
        questions.append("What is the main specialist question we want answered from this visit?")
    if visit_type in {"urgent-care", "telehealth"}:
        questions.append("What symptoms or changes would mean I should escalate care after this visit?")
    for item in follow_up[:2]:
        task = item.get("task")
        if task:
            questions.append(task)
    for item in unresolved[:2]:
        text = item.get("text")
        if text:
            questions.append(text)
    deduped = []
    for question in questions:
        if question and question not in deduped:
            deduped.append(question)
    return deduped[:4]


def note_summaries(root: Path, person_id: str, limit: int) -> list[str]:
    summaries = []
    for note_path in recent_notes(root, person_id, limit):
        lines = note_path.read_text(encoding="utf-8").strip().splitlines()
        title = lines[0].removeprefix("# ").strip() if lines else note_path.stem
        body = " ".join(
            line.strip()
            for line in lines[1:]
            if line.strip() and not line.startswith("- ")
        )
        summaries.append(f"{title}: {body}".strip())
    return summaries


def render_section(title: str, items: list[str]) -> str:
    body = "\n".join(f"- {item}" for item in items) if items else "- none recorded"
    return f"## {title}\n{body}"


def build_handoff(
    root: Path,
    person_id: str,
    reason: str,
    visit_type: str,
    note_limit: int,
) -> str:
    profile = load_profile(root, person_id)
    conflicts = load_conflicts(root, person_id)
    open_conflicts = [item for item in conflicts if item["status"] == "open"]

    parts = [
        "# Clinician Handoff",
        "",
        f"## Visit Type\n- {visit_type}",
        "",
        f"## Reason for Visit\n- {reason}",
        "",
        f"## Patient\n- {profile.get('name') or person_id}",
        f"- Date of birth: {profile.get('date_of_birth') or 'unknown'}",
        f"- Sex: {profile.get('sex') or 'unknown'}",
        "",
        f"## Visit Focus\n- {VISIT_HINTS[visit_type]}",
        "",
        render_section(
            "Known Conditions",
            [render_record(item, ("name", "status")) for item in profile.get("conditions", [])],
        ),
        "",
        render_section(
            "Current Medications",
            [render_record(item, ("name", "dose", "form", "frequency", "status")) for item in profile.get("medications", [])],
        ),
        "",
        render_section(
            "Allergies",
            [render_record(item, ("substance", "reaction", "severity")) for item in profile.get("allergies", [])],
        ),
        "",
        render_section(
            "Recent Tests",
            [render_record(item, ("name", "value", "unit", "flag", "date")) for item in profile.get("recent_tests", [])],
        ),
        "",
        render_section(
            "Recent Encounters",
            [render_record(item, ("date", "title", "summary")) for item in profile.get("encounters", [])[:5]],
        ),
        "",
        render_section("Recent Notes", note_summaries(root, person_id, note_limit)),
        "",
        render_section("Suggested Questions", suggested_questions(profile, visit_type)),
        "",
        render_section(
            "Open Data Conflicts",
            [
                f"{item['section']} `{item['identity']}` field `{item['field']}` differs between sources"
                for item in open_conflicts
            ],
        ),
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a clinician handoff")
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", default="")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--visit-type", choices=sorted(VISIT_HINTS), default="pcp")
    parser.add_argument("--note-limit", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root)
    handoff = build_handoff(root, args.person_id, args.reason, args.visit_type, args.note_limit)
    output_path = exports_dir(root, args.person_id) / f"clinician_handoff_{args.visit_type}.md"
    atomic_write_text(output_path, handoff + "\n")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
