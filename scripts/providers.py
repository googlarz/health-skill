#!/usr/bin/env python3
"""Provider directory: store the user's care team.

Providers live in HEALTH_PROFILE.json under `providers`. Each entry has:
  id, name, role, organization, phone, portal_url, last_visit, next_visit, notes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_profile,
        providers_path,
        save_profile,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_profile,
        providers_path,
        save_profile,
        workspace_lock,
    )


COMMON_ROLES = {
    "pcp": "Primary Care Physician",
    "gyn": "Gynecologist",
    "ob": "OB/GYN",
    "cardio": "Cardiologist",
    "endo": "Endocrinologist",
    "derm": "Dermatologist",
    "ortho": "Orthopedist",
    "neuro": "Neurologist",
    "psych": "Psychiatrist",
    "therapist": "Therapist",
    "pt": "Physical Therapist",
    "dentist": "Dentist",
    "optom": "Optometrist",
    "ophth": "Ophthalmologist",
    "rheum": "Rheumatologist",
    "gi": "Gastroenterologist",
    "onco": "Oncologist",
    "uro": "Urologist",
    "ent": "ENT",
}


def _next_id(providers: list[dict[str, Any]]) -> str:
    nums = [int(p.get("id", "p0").lstrip("p")) for p in providers if str(p.get("id", "")).startswith("p")]
    return f"p{max(nums) + 1 if nums else 1}"


def add_provider(
    root: Path,
    person_id: str,
    name: str,
    role: str,
    organization: str = "",
    phone: str = "",
    portal_url: str = "",
    last_visit: str = "",
    next_visit: str = "",
    notes: str = "",
) -> dict[str, Any]:
    role_full = COMMON_ROLES.get(role.lower(), role)
    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        providers = list(profile.get("providers", []))
        provider = {
            "id": _next_id(providers),
            "name": name,
            "role": role_full,
            "organization": organization,
            "phone": phone,
            "portal_url": portal_url,
            "last_visit": last_visit,
            "next_visit": next_visit,
            "notes": notes,
            "created_at": date.today().isoformat(),
        }
        providers.append(provider)
        profile["providers"] = providers
        save_profile(root, person_id, profile)
    return provider


def render_providers_md(root: Path, person_id: str) -> str:
    profile = load_profile(root, person_id)
    providers = profile.get("providers", [])
    lines = ["# Care Team\n"]
    if not providers:
        lines.append("No providers on file yet.")
        lines.append("")
        lines.append("Add one with:")
        lines.append("```")
        lines.append("scripts/care_workspace.py add-provider --root . \\")
        lines.append('  --name "Dr. Smith" --role pcp --organization "City Health" \\')
        lines.append('  --phone "555-1234" --last-visit 2025-09-15')
        lines.append("```")
        return "\n".join(lines) + "\n"

    for p in providers:
        lines.append(f"## {p.get('name', '?')} — _{p.get('role', '?')}_")
        lines.append("")
        if p.get("organization"):
            lines.append(f"- Organization: {p['organization']}")
        if p.get("phone"):
            lines.append(f"- Phone: {p['phone']}")
        if p.get("portal_url"):
            lines.append(f"- Portal: {p['portal_url']}")
        if p.get("last_visit"):
            lines.append(f"- Last visit: {p['last_visit']}")
        if p.get("next_visit"):
            lines.append(f"- Next visit: {p['next_visit']}")
        if p.get("notes"):
            lines.append(f"- Notes: {p['notes']}")
        lines.append("")
    lines.append(f"_Generated {date.today().isoformat()}_")
    return "\n".join(lines) + "\n"


def write_providers(root: Path, person_id: str) -> Path:
    text = render_providers_md(root, person_id)
    path = providers_path(root, person_id)
    atomic_write_text(path, text)
    return path
