#!/usr/bin/env python3
"""
UserPromptSubmit hook — detect health data in user prompts, extract structured
insights, and ingest them into:
  1. context-mode session DB  (searchable via ctx_search)
  2. health workspace profile  (structured timeline data)

Raw prompt text is NEVER stored — only extracted facts and insights.
Writes /tmp/health-ingest-{session_id}.json for the Stop hook to display.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path


# ── Workspace detection ───────────────────────────────────────────────────────

def _is_workspace(p: Path) -> bool:
    """Detect any health workspace layout."""
    if not p.is_dir():
        return False
    # health-skill JSON layout
    if (p / "HEALTH_PROFILE.json").exists() or (p / "people").is_dir():
        return True
    # markdown layout: HEALTH_PROFILE.md directly or person subdirs with it
    if (p / "HEALTH_PROFILE.md").exists():
        return True
    if any((p / d / "HEALTH_PROFILE.md").exists() for d in ("Dawid", "Joanna") if (p / d).is_dir()):
        return True
    return False


def _is_person_dir(p: Path) -> bool:
    return p.is_dir() and (p / "HEALTH_PROFILE.md").exists()


def find_workspace(input_data: dict) -> Path | None:
    env_root = os.environ.get("HEALTH_WORKSPACE_ROOT")
    if env_root:
        p = Path(env_root)
        if _is_workspace(p):
            return p

    candidates: list[Path] = []
    for key in ("cwd", "project_dir", "input_project_dir"):
        val = input_data.get(key)
        if val:
            candidates.append(Path(val))
    for r in input_data.get("workspace_roots", []):
        candidates.append(Path(r))

    for c in candidates:
        if not c.exists():
            continue
        if _is_workspace(c):
            # If c itself is a person dir (has HEALTH_PROFILE.md and parent is workspace root)
            # return the parent so person detection works correctly
            if (c / "HEALTH_PROFILE.md").exists() and _is_workspace(c.parent):
                return c.parent
            return c
        for sub in ("care-workspace", "health-workspace", "workspace"):
            if _is_workspace(c / sub):
                return c / sub
        for parent in [c.parent, c.parent.parent]:
            if _is_workspace(parent):
                return parent
    return None


def find_person_id(root: Path, input_data: dict | None = None) -> str:
    """Return person id/name. For markdown workspaces, infer from cwd."""
    # If cwd is inside a person dir, use that
    if input_data:
        cwd = input_data.get("cwd") or input_data.get("project_dir") or ""
        cwd_path = Path(cwd)
        # Check if cwd itself is a named person dir under root
        if cwd_path.parent == root and _is_person_dir(cwd_path):
            return cwd_path.name
        # Check if cwd is deeper inside a person subdir of root
        try:
            rel = cwd_path.relative_to(root)
            first_part = str(rel).split(os.sep)[0]
            if first_part and first_part != "." and _is_person_dir(root / first_part):
                return first_part
        except ValueError:
            pass

    # health-skill JSON layout
    if (root / "HEALTH_PROFILE.json").exists():
        return ""
    people = root / "people"
    if people.is_dir():
        for entry in sorted(people.iterdir()):
            if entry.is_dir() and (entry / "profile.json").exists():
                return entry.name

    # markdown layout: default to first person dir found
    for entry in sorted(root.iterdir()):
        if _is_person_dir(entry):
            return entry.name
    return ""


# ── Health data classification ────────────────────────────────────────────────

_WORKOUT_SIGNALS = re.compile(
    r"\b(ran|run|jog|cycling|swim|deadlift|squat|bench|press|pull.?up|push.?up|"
    r"sets?|reps?|km|miles?|pace|heart rate|vo2|cardio|workout|"
    r"training|lifting|session|gym|crossfit|hiit|interval|sprint|walked?)\b",
    re.IGNORECASE,
)
_CHECKIN_SIGNALS = re.compile(
    r"\b(mood|energy|pain|sleep|slept|fatigue|tired|anxious|anxiety|"
    r"stress|depressed|feel(?:ing)?|sick|nausea|headache|dizzy|fever|"
    r"sore|ache|cramp|bloat|today i feel|m\d|s\d|e\d|p\d)\b",
    re.IGNORECASE,
)
_LAB_SIGNALS = re.compile(
    r"\b(tsh|ldl|hdl|a1c|hba1c|glucose|creatinine|alt|ast|bun|cbc|"
    r"cholesterol|triglyceride|hemoglobin|wbc|rbc|ferritin|vitamin\s*d|"
    r"lab|result|blood test|panel)\b",
    re.IGNORECASE,
)
_NUTRITION_SIGNALS = re.compile(
    r"\b(ate|eat|meal|breakfast|lunch|dinner|snack|calories|kcal|protein|"
    r"carb|fat|fiber|sodium|chicken|rice|pasta|salad|fruit|vegetable)\b",
    re.IGNORECASE,
)
_WEIGHT_SIGNALS = re.compile(
    r"\b(weight|weigh|weighed|scale)\b.*\b(\d{2,3}(?:\.\d)?)\s*(kg|lbs?|pounds?|kilos?)\b",
    re.IGNORECASE,
)
_MED_SIGNALS = re.compile(
    r"\b(started|stopped|took|taking|prescribed)\b.{0,40}\b(mg|mcg)\b",
    re.IGNORECASE,
)


def classify(text: str) -> list[str]:
    types = []
    if _WORKOUT_SIGNALS.search(text):
        types.append("workout")
    if _CHECKIN_SIGNALS.search(text):
        types.append("checkin")
    if _LAB_SIGNALS.search(text):
        types.append("labs")
    if _NUTRITION_SIGNALS.search(text):
        types.append("nutrition")
    if _WEIGHT_SIGNALS.search(text):
        types.append("weight")
    if _MED_SIGNALS.search(text):
        types.append("medication")
    return types


# ── context-mode session DB ───────────────────────────────────────────────────

def _ctx_db_path(project_dir: str) -> Path | None:
    h = hashlib.sha256(project_dir.encode()).hexdigest()[:16]
    db_dir = Path.home() / ".claude" / "context-mode" / "sessions"
    # Prefer exact match, else latest worktree variant
    exact = db_dir / f"{h}.db"
    if exact.exists():
        return exact
    variants = sorted(db_dir.glob(f"{h}__*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if variants:
        return variants[0]
    return None


def _find_db_for_session(session_id: str, project_dir: str) -> Path | None:
    """Find context-mode session DB by project dir hash, falling back to session_id scan."""
    db_dir = Path.home() / ".claude" / "context-mode" / "sessions"
    if not db_dir.exists():
        return None
    # Try project dir hash first
    candidate = _ctx_db_path(project_dir)
    if candidate:
        return candidate
    # Fall back: scan all DBs for this session_id
    for db in sorted(db_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT 1 FROM session_meta WHERE session_id=? LIMIT 1", (session_id,)
            ).fetchone()
            conn.close()
            if row:
                return db
        except Exception:
            continue
    return None


def insert_ctx_events(session_id: str, project_dir: str, events: list[dict]) -> bool:
    """Insert health insight events into context-mode session DB."""
    db_path = _find_db_for_session(session_id, project_dir)
    if not db_path:
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        for ev in events:
            data_hash = hashlib.sha256(ev["data"].encode()).hexdigest()[:16]
            conn.execute(
                "INSERT OR IGNORE INTO session_events "
                "(session_id, type, category, priority, data, source_hook, data_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, ev["type"], ev["category"], ev["priority"],
                 ev["data"], "UserPromptSubmit:health-auto-ingest", data_hash),
            )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Ingestion ─────────────────────────────────────────────────────────────────

def _load_health_scripts(root: Path) -> bool:
    for candidate in [
        Path(__file__).parent.parent / "scripts",  # hooks/ → repo root → scripts/
        root / "scripts",
        root.parent / "scripts",
    ]:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return True
    return False


def _person_dir(root: Path, person_id: str) -> Path:
    if person_id and (root / person_id).is_dir():
        return root / person_id
    return root


def _is_markdown_workspace(root: Path, person_id: str) -> bool:
    d = _person_dir(root, person_id)
    return (d / "HEALTH_PROFILE.md").exists()


def _append_timeline(root: Path, person_id: str, entry: str) -> None:
    """Append a dated entry to HEALTH_TIMELINE.md in the person's directory."""
    d = _person_dir(root, person_id)
    timeline = d / "HEALTH_TIMELINE.md"
    if not timeline.exists():
        timeline.write_text("# Health Timeline\n\n")
    with open(timeline, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def ingest(root: Path, person_id: str, prompt: str, types: list[str],
           session_id: str, project_dir: str, input_data: dict | None = None) -> list[str]:
    _load_health_scripts(root)
    saved = []
    ctx_events: list[dict] = []
    today = date.today().isoformat()

    if "workout" in types:
        try:
            from training import parse_workout
            workout = parse_workout(prompt)
            if workout.get("exercises") or workout.get("type") or workout.get("distance_km"):
                label = workout.get("type") or "workout"
                dur = workout.get("duration_min")
                dist = workout.get("distance_km")
                parts = [label]
                if dist:
                    parts.append(f"{dist}km")
                if dur:
                    parts.append(f"{dur}min")
                summary = " · ".join(str(p) for p in parts)
                if _is_markdown_workspace(root, person_id):
                    _append_timeline(root, person_id,
                        f"\n## {today} — Workout\n- {summary}\n"
                        + (f"- Duration: {dur} min\n" if dur else "")
                        + (f"- Distance: {dist} km\n" if dist else "")
                    )
                else:
                    from training import log_workout
                    log_workout(root, person_id, workout)
                saved.append(f"🏋️ Workout: {summary}")
                ctx_events.append({
                    "type": "health_workout",
                    "category": "health",
                    "priority": 1,
                    "data": f"[{today}] workout: {summary}",
                })
        except Exception:
            pass

    if "checkin" in types:
        try:
            from checkins import parse_checkin
            parsed = parse_checkin(prompt)
            metrics = {k: v for k, v in parsed.items()
                       if k in ("mood", "energy", "pain", "sleep_hours") and v is not None}
            notes = parsed.get("notes", "").strip()
            if metrics or notes:
                parts = [f"{k}={v}" for k, v in metrics.items()]
                if notes:
                    parts.append(f"notes='{notes}'")
                if _is_markdown_workspace(root, person_id):
                    lines = "\n".join(f"- {p}" for p in parts)
                    _append_timeline(root, person_id, f"\n## {today} — Check-in\n{lines}\n")
                else:
                    from checkins import save_checkin
                    save_checkin(root, person_id, parsed)
                saved.append(f"📊 Check-in: {', '.join(parts)}")
                ctx_events.append({
                    "type": "health_checkin",
                    "category": "health",
                    "priority": 1,
                    "data": f"[{today}] check-in: {', '.join(parts)}",
                })
        except Exception:
            pass

    if "nutrition" in types:
        try:
            from nutrition import log_meal
            result = log_meal(root, person_id, prompt)
            kcal = result.get("total_kcal", 0)
            items_list = result.get("items", [])
            if items_list:
                food_names = ", ".join(i.get("name", "") for i in items_list[:4])
                saved.append(f"🍽 Meal: {food_names} (~{round(kcal)} kcal)")
                ctx_events.append({
                    "type": "health_meal",
                    "category": "health",
                    "priority": 2,
                    "data": f"[{today}] meal: {food_names} | {round(kcal)} kcal | "
                            f"protein {result.get('total_protein_g', 0):.0f}g",
                })
        except Exception:
            pass

    if "labs" in types:
        try:
            from extraction import extract_lab_candidates
            candidates = extract_lab_candidates(prompt, today)
            auto = [c for c in candidates if c.get("auto_apply")]
            if auto:
                names = ", ".join(f"{c['candidate']['name']} {c['candidate']['value']}{c['candidate']['unit']}"
                                  for c in auto[:4])
                if _is_markdown_workspace(root, person_id):
                    lines = "\n".join(
                        f"- {c['candidate']['name']}: {c['candidate']['value']} {c['candidate']['unit']}"
                        for c in auto
                    )
                    _append_timeline(root, person_id, f"\n## {today} — Labs\n{lines}\n")
                else:
                    from care_workspace import upsert_record
                    for c in auto:
                        upsert_record(root, person_id, "recent_tests", c["candidate"],
                                      source_type="prompt", source_label="auto-ingest",
                                      source_date=c["candidate"].get("date", today))
                saved.append(f"🧪 Labs: {names}")
                ctx_events.append({
                    "type": "health_labs",
                    "category": "health",
                    "priority": 1,
                    "data": f"[{today}] labs: {names}",
                })
        except Exception:
            pass

    if "weight" in types:
        try:
            m = _WEIGHT_SIGNALS.search(prompt)
            if m:
                val = float(m.group(2))
                unit = "kg" if m.group(3).lower().startswith("k") else "lbs"
                if _is_markdown_workspace(root, person_id):
                    _append_timeline(root, person_id, f"\n## {today} — Weight\n- {val} {unit}\n")
                else:
                    from care_workspace import record_weight
                    record_weight(root, person_id, today, val, unit)
                saved.append(f"⚖️ Weight: {val} {unit}")
                ctx_events.append({
                    "type": "health_weight",
                    "category": "health",
                    "priority": 2,
                    "data": f"[{today}] weight: {val} {unit}",
                })
        except Exception:
            pass

    if ctx_events and project_dir:
        insert_ctx_events(session_id, project_dir, ctx_events)

    return saved


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        return

    prompt = (data.get("prompt") or data.get("message") or "").strip()
    if not prompt or len(prompt) < 10:
        return

    # Skip system-injected content
    if any(prompt.startswith(tag) for tag in (
        "<task-notification>", "<system-reminder>", "<context_guidance>", "<tool-result>"
    )):
        return

    types = classify(prompt)
    if not types:
        return

    root = find_workspace(data)
    if not root:
        return

    person_id = find_person_id(root, data)
    session_id = data.get("session_id", "")
    project_dir = data.get("cwd") or data.get("project_dir") or ""

    saved = ingest(root, person_id, prompt, types, session_id, project_dir, data)

    if saved and session_id:
        Path(f"/tmp/health-ingest-{session_id}.json").write_text(json.dumps({"lines": saved}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
