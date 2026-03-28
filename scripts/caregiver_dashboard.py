#!/usr/bin/env python3
"""Build a caregiver dashboard across multiple person project folders."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path


def discover_projects(root: Path) -> list[Path]:
    projects = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and (candidate / "HEALTH_PROFILE.json").exists():
            projects.append(candidate)
    return projects


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_weight_entries(project: Path) -> list[dict]:
    db_path = project / "health_metrics.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT entry_date, value, unit FROM weight_entries ORDER BY entry_date ASC, id ASC"
        ).fetchall()
    return [{"entry_date": row[0], "value": row[1], "unit": row[2]} for row in rows]


def urgency_bucket(score: int) -> str:
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def collect_project_rows(root: Path) -> list[dict]:
    project_rows = []
    for project in discover_projects(root):
        profile = load_json(project / "HEALTH_PROFILE.json")
        conflicts = load_json(project / "HEALTH_CONFLICTS.json") if (project / "HEALTH_CONFLICTS.json").exists() else []
        review_queue = load_json(project / "HEALTH_REVIEW_QUEUE.json") if (project / "HEALTH_REVIEW_QUEUE.json").exists() else []
        inbox_count = len([p for p in (project / "inbox").iterdir()]) if (project / "inbox").exists() else 0
        open_conflicts = sum(1 for item in conflicts if item.get("status") == "open")
        open_reviews = sum(1 for item in review_queue if item.get("status") == "open")
        abnormal_labs = sum(
            1
            for item in profile.get("recent_tests", [])
            if item.get("flag") in {"high", "low", "abnormal"}
        )
        overdue_follow_ups = sum(
            1
            for item in profile.get("follow_up", [])
            if item.get("due_date")
            and item.get("status") != "done"
            and item.get("due_date") < date.today().isoformat()
        )
        weight_entries = load_weight_entries(project)
        weight_signal = 0
        if len(weight_entries) >= 2:
            first = weight_entries[0]["value"]
            latest = weight_entries[-1]["value"]
            if first:
                change_pct = abs((latest - first) / first)
                if change_pct >= 0.05:
                    weight_signal = 1
        urgency_score = (
            inbox_count
            + open_conflicts * 2
            + open_reviews
            + abnormal_labs * 2
            + overdue_follow_ups * 3
            + weight_signal
        )

        follow_up_lines = []
        reminder_lines = []
        for item in profile.get("follow_up", [])[:5]:
            task = item.get("task")
            due_date = item.get("due_date")
            status = item.get("status")
            if task:
                parts = [task]
                if due_date:
                    parts.append(due_date)
                if status:
                    parts.append(status)
                line = " | ".join(parts)
                follow_up_lines.append(line)
                if status != "done":
                    reminder_lines.append(line)

        project_rows.append(
            {
                "name": profile.get("name") or project.name,
                "folder": project.name,
                "inbox_count": inbox_count,
                "open_conflicts": open_conflicts,
                "open_reviews": open_reviews,
                "abnormal_labs": abnormal_labs,
                "overdue_follow_ups": overdue_follow_ups,
                "urgency_score": urgency_score,
                "urgency": urgency_bucket(urgency_score),
                "last_updated": profile.get("audit", {}).get("updated_at") or "unknown",
                "follow_up_lines": follow_up_lines,
                "reminder_lines": reminder_lines,
                "medication_count": len(profile.get("medications", [])),
                "primary_caregiver": profile.get("preferences", {}).get("primary_caregiver", ""),
                "reason_lines": [
                    reason
                    for reason in [
                        f"{inbox_count} inbox file(s)" if inbox_count else "",
                        f"{open_conflicts} open conflict(s)" if open_conflicts else "",
                        f"{open_reviews} review item(s)" if open_reviews else "",
                        f"{abnormal_labs} abnormal lab flag(s)" if abnormal_labs else "",
                        f"{overdue_follow_ups} overdue follow-up(s)" if overdue_follow_ups else "",
                    ]
                    if reason
                ],
            }
        )
    return project_rows


def build_dashboard(root: Path, min_urgency: str = "low") -> str:
    projects = discover_projects(root)
    project_rows = collect_project_rows(root)
    lines = [
        "# Caregiver Dashboard",
        "",
        "This view is meant to help you steady the week, not make you feel behind.",
        "",
        f"- Projects found: {len(projects)}",
        "",
    ]
    if not projects:
        lines.append("No person project folders found.")
        lines.append("")
        return "\n".join(lines)

    urgency_order = {"low": 0, "medium": 1, "high": 2}
    filtered_rows = [
        row for row in project_rows if urgency_order[row["urgency"]] >= urgency_order[min_urgency]
    ]

    lines.extend(["## If You Only Have Time For A Few Things"])
    action_items = []
    for row in sorted(project_rows, key=lambda item: (-item["urgency_score"], item["name"].lower())):
        if row["inbox_count"]:
            action_items.append(f"{row['name']}: process inbox ({row['inbox_count']} pending)")
        if row["open_conflicts"]:
            action_items.append(f"{row['name']}: resolve {row['open_conflicts']} conflicts")
        if row["overdue_follow_ups"]:
            action_items.append(f"{row['name']}: {row['overdue_follow_ups']} overdue follow-ups")
    if action_items:
        lines.extend(f"- {item}" for item in action_items[:8])
    else:
        lines.append("- no urgent actions today")
    lines.append("")

    needs_attention = [
        row for row in sorted(filtered_rows, key=lambda item: (-item["urgency_score"], item["name"].lower()))
        if row["urgency"] in {"high", "medium"}
    ]
    steady_rows = [
        row for row in sorted(filtered_rows, key=lambda item: (-item["urgency_score"], item["name"].lower()))
        if row["urgency"] == "low"
    ]

    lines.append("## Attention First")
    if not needs_attention:
        lines.append("- Nobody is in the medium or high urgency bucket right now.")
        lines.append("")
    for row in needs_attention:
        lines.extend(
            [
                f"## {row['name']}",
                f"- Folder: `{row['folder']}`",
                f"- Urgency: {row['urgency']} ({row['urgency_score']})",
                f"- Pending inbox files: {row['inbox_count']}",
                f"- Open conflicts: {row['open_conflicts']}",
                f"- Open review items: {row['open_reviews']}",
                f"- Abnormal lab flags: {row['abnormal_labs']}",
                f"- Overdue follow-ups: {row['overdue_follow_ups']}",
                f"- Structured medication list entries: {row['medication_count']}",
                f"- Last updated: {row['last_updated']}",
                "### Why This Person Rose To The Top",
            ]
        )
        if row["reason_lines"]:
            lines.extend(f"- {item}" for item in row["reason_lines"])
        else:
            lines.append("- No specific pressure signal is recorded.")
        lines.append("### Top Follow Up")
        if row["follow_up_lines"]:
            lines.extend(f"- {item}" for item in row["follow_up_lines"])
        else:
            lines.append("- none recorded")
        lines.append("### Unresolved Work")
        unresolved = []
        if row["open_conflicts"]:
            unresolved.append(f"{row['open_conflicts']} conflicts")
        if row["open_reviews"]:
            unresolved.append(f"{row['open_reviews']} review items")
        if row["abnormal_labs"]:
            unresolved.append(f"{row['abnormal_labs']} abnormal lab flags")
        if unresolved:
            lines.extend(f"- {item}" for item in unresolved)
        else:
            lines.append("- none recorded")
        lines.append("")

    lines.append("## Can Likely Wait")
    if steady_rows:
        for row in steady_rows:
            lines.append(
                f"- {row['name']} | urgency {row['urgency']} ({row['urgency_score']}) | "
                f"inbox {row['inbox_count']} | conflicts {row['open_conflicts']} | reviews {row['open_reviews']}"
            )
    else:
        lines.append("- Nobody is in the low-urgency bucket right now.")
    lines.append("")
    lines.append("## Reminders By Person")
    for row in sorted(project_rows, key=lambda item: item["name"].lower()):
        lines.append(f"### {row['name']}")
        if row["reminder_lines"]:
            lines.extend(f"- {item}" for item in row["reminder_lines"][:5])
        else:
            lines.append("- no active reminders recorded")
    lines.append("")
    return "\n".join(lines)


def build_weekly_summary(root: Path) -> str:
    dashboard = build_dashboard(root)
    lines = [
        "# Caregiver Weekly Summary",
        "",
        "Use this as the weekly review and planning note for all tracked person folders.",
        "",
        dashboard,
    ]
    return "\n".join(lines)


def build_caregiver_handoff(root: Path) -> str:
    rows = sorted(collect_project_rows(root), key=lambda item: (-item["urgency_score"], item["name"].lower()))
    lines = [
        "# Caregiver Handoff",
        "",
        "Use this when one caregiver is handing over the week to another.",
        "",
    ]
    if not rows:
        lines.append("No person project folders found.")
        lines.append("")
        return "\n".join(lines)

    for row in rows:
        lines.extend(
            [
                f"## {row['name']}",
                f"- Urgency: {row['urgency']} ({row['urgency_score']})",
                f"- Primary caregiver: {row['primary_caregiver'] or 'not recorded'}",
                f"- Last updated: {row['last_updated']}",
                "- What needs watching:",
            ]
        )
        if row["reason_lines"]:
            lines.extend(f"- {item}" for item in row["reason_lines"])
        else:
            lines.append("- no major pressure signals recorded")
        lines.append("- Next reminders:")
        if row["reminder_lines"]:
            lines.extend(f"- {item}" for item in row["reminder_lines"][:5])
        else:
            lines.append("- none recorded")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build caregiver dashboard")
    parser.add_argument("--root", required=True, help="Parent folder containing person project folders")
    parser.add_argument("--min-urgency", choices=["low", "medium", "high"], default="low")
    parser.add_argument("--weekly-summary", action="store_true")
    parser.add_argument("--handoff", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    if args.handoff:
        output = build_caregiver_handoff(root)
        path = root / "CAREGIVER_HANDOFF.md"
    elif args.weekly_summary:
        output = build_weekly_summary(root)
        path = root / "CAREGIVER_WEEKLY_SUMMARY.md"
    else:
        output = build_dashboard(root, args.min_urgency)
        path = root / "CAREGIVER_DASHBOARD.md"
    path.write_text(output, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
