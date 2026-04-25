#!/usr/bin/env python3
"""Household / family graph.

Beyond a single person folder, a household has multiple people with
relationships. This module:

- Manages HOUSEHOLD.json at workspace root listing members + relationships
- Cascades family medical history: when person A gets a "breast cancer at 48"
  condition, person B (daughter) automatically gains that as family_history
- Builds a shared medication list across the household for cross-conflict checks
- Renders HOUSEHOLD_DASHBOARD.md with all members + cross-cutting concerns

Data model (HOUSEHOLD.json):
{
  "members": [
    {"id": "mom",   "name": "Sarah", "folder": "mom",   "date_of_birth": "1965-03-12", "sex": "female"},
    {"id": "self",  "name": "Anna",  "folder": "anna",  "date_of_birth": "1990-07-08", "sex": "female"},
    {"id": "kid",   "name": "Lily",  "folder": "lily",  "date_of_birth": "2018-04-15", "sex": "female"}
  ],
  "relationships": [
    {"from": "self", "to": "mom", "type": "mother"},
    {"from": "kid",  "to": "self", "type": "mother"}
  ]
}
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        household_dashboard_path,
        household_path,
        load_profile,
        save_profile,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        household_dashboard_path,
        household_path,
        load_profile,
        save_profile,
    )


def load_household(root: Path) -> dict[str, Any]:
    p = household_path(root)
    if not p.exists():
        return {"members": [], "relationships": []}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"members": [], "relationships": []}


def save_household(root: Path, data: dict[str, Any]) -> None:
    atomic_write_text(household_path(root), json.dumps(data, indent=2) + "\n")


def add_member(
    root: Path,
    member_id: str,
    name: str,
    folder: str,
    date_of_birth: str = "",
    sex: str = "",
) -> dict[str, Any]:
    hh = load_household(root)
    hh["members"] = [m for m in hh["members"] if m.get("id") != member_id]
    member = {
        "id": member_id,
        "name": name,
        "folder": folder,
        "date_of_birth": date_of_birth,
        "sex": sex,
    }
    hh["members"].append(member)
    save_household(root, hh)
    return member


def add_relationship(root: Path, from_id: str, to_id: str, rel_type: str) -> dict[str, Any]:
    hh = load_household(root)
    rel = {"from": from_id, "to": to_id, "type": rel_type}
    # Dedup
    hh["relationships"] = [r for r in hh["relationships"]
                           if not (r.get("from") == from_id and r.get("to") == to_id)]
    hh["relationships"].append(rel)
    save_household(root, hh)
    return rel


# Cancer/cardiac terms that should cascade as family history
CASCADE_TERMS = [
    "breast cancer", "ovarian cancer", "colon cancer", "colorectal cancer",
    "prostate cancer", "skin cancer", "melanoma", "cervical cancer",
    "heart attack", "myocardial infarction", "stroke",
    "early cardiac death", "diabetes", "alzheimer", "parkinson",
]


def _condition_should_cascade(condition_name: str) -> bool:
    n = (condition_name or "").lower()
    return any(term in n for term in CASCADE_TERMS)


def cascade_family_history(root: Path) -> dict[str, Any]:
    """Walk household graph and ensure each member's family_history reflects
    the conditions of their relatives.

    Returns a summary of changes.
    """
    hh = load_household(root)
    members = {m["id"]: m for m in hh.get("members", [])}
    relationships = hh.get("relationships", [])

    # Build: for each member, who are their first-degree relatives and what relation
    relatives_of: dict[str, list[tuple[str, str]]] = {}  # member_id -> [(relative_id, relation_to_member)]
    for r in relationships:
        # r is from->to with type. Type describes relation OF "to" RELATIVE TO "from".
        # E.g. {from: self, to: mom, type: mother} means: self's mother is mom.
        relatives_of.setdefault(r["from"], []).append((r["to"], r["type"]))
        # Reverse for child-of-parent
        reverse_map = {"mother": "child", "father": "child", "parent": "child",
                       "sister": "sibling", "brother": "sibling", "sibling": "sibling",
                       "child": "parent", "daughter": "parent", "son": "parent"}
        rev_type = reverse_map.get(r["type"])
        if rev_type:
            relatives_of.setdefault(r["to"], []).append((r["from"], rev_type))

    changes = {"members_updated": 0, "entries_added": 0}

    for member_id, member in members.items():
        relatives = relatives_of.get(member_id, [])
        if not relatives:
            continue
        # Load this member's profile and their relatives' profiles
        try:
            profile = load_profile(root, member["folder"])
        except Exception:
            continue
        existing_fh = profile.get("family_history", []) or []
        existing_keys = {(f.get("relation"), f.get("condition")) for f in existing_fh}
        added_here = 0

        for rel_id, relation in relatives:
            rel_member = members.get(rel_id)
            if not rel_member:
                continue
            try:
                rel_profile = load_profile(root, rel_member["folder"])
            except Exception:
                continue
            for c in rel_profile.get("conditions", []) or []:
                cname = c.get("name", "")
                if not _condition_should_cascade(cname):
                    continue
                # Compute age at diagnosis if we have data
                age_at_dx = ""
                if c.get("diagnosed_date") and rel_member.get("date_of_birth"):
                    try:
                        dx = datetime.strptime(c["diagnosed_date"][:10], "%Y-%m-%d").date()
                        dob = datetime.strptime(rel_member["date_of_birth"][:10], "%Y-%m-%d").date()
                        age_at_dx = str(int((dx - dob).days // 365))
                    except ValueError:
                        pass
                key = (relation, cname)
                if key in existing_keys:
                    continue
                existing_fh.append({
                    "relation": relation,
                    "condition": cname,
                    "age_at_diagnosis": age_at_dx,
                    "source": f"household_cascade:{rel_member['folder']}",
                })
                existing_keys.add(key)
                added_here += 1

        if added_here:
            profile["family_history"] = existing_fh
            save_profile(root, member["folder"], profile)
            changes["members_updated"] += 1
            changes["entries_added"] += added_here

    return changes


def shared_medications(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return mapping of member_id -> medications list, for cross-checks."""
    hh = load_household(root)
    out: dict[str, list[dict[str, Any]]] = {}
    for m in hh.get("members", []):
        try:
            p = load_profile(root, m["folder"])
            out[m["id"]] = p.get("medications", [])
        except Exception:
            out[m["id"]] = []
    return out


def render_household_dashboard(root: Path) -> str:
    hh = load_household(root)
    today = date.today()
    lines = [f"# Household Dashboard", "",
             f"_Generated {today.isoformat()}_", ""]
    if not hh.get("members"):
        lines.append("No household members configured.")
        lines.append("")
        lines.append("Add members with:")
        lines.append("```")
        lines.append('scripts/care_workspace.py household-add-member \\')
        lines.append('  --root . --id self --name "Anna" --folder anna \\')
        lines.append('  --date-of-birth 1990-07-08 --sex female')
        lines.append("```")
        return "\n".join(lines) + "\n"

    lines.append("## Members")
    lines.append("")
    for m in hh["members"]:
        lines.append(f"- **{m['name']}** (`{m['id']}`) — folder: `{m['folder']}`"
                     + (f" · DOB {m['date_of_birth']}" if m.get('date_of_birth') else "")
                     + (f" · {m['sex']}" if m.get('sex') else ""))
    lines.append("")

    if hh.get("relationships"):
        lines.append("## Relationships")
        lines.append("")
        for r in hh["relationships"]:
            lines.append(f"- {r['from']} → {r['to']}: {r['type']}")
        lines.append("")

    # Cross-cutting summary
    meds_by_member = shared_medications(root)
    if any(meds for meds in meds_by_member.values()):
        lines.append("## Medications across household")
        lines.append("")
        for m in hh["members"]:
            ml = meds_by_member.get(m["id"], [])
            if ml:
                lines.append(f"### {m['name']}")
                for med in ml:
                    lines.append(f"- {med.get('name','?')} {med.get('dose','')} {med.get('frequency','')}")
                lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Run `household-cascade` after adding new conditions to a member to update everyone's family history automatically.")
    lines.append("- Each member folder retains its own private profile, dashboard, and inbox.")
    return "\n".join(lines) + "\n"


def write_household_dashboard(root: Path) -> Path:
    text = render_household_dashboard(root)
    path = household_dashboard_path(root)
    atomic_write_text(path, text)
    return path
