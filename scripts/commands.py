#!/usr/bin/env python3
"""CLI commands and argument parser for Health Skill."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

# NOTE: keep both import blocks in sync
try:
    from .care_workspace import (
        DEFAULT_PROFILE,
        RECORD_KEYS,
        atomic_write_text,
        calendar_export_path,
        care_status_path,
        change_report_path,
        conflicts_path,
        dossier_path,
        ensure_person,
        exports_dir,
        home_path,
        intake_summary_path,
        load_conflicts,
        load_medication_history,
        load_profile,
        load_review_queue,
        list_inbox_files,
        load_vital_entries,
        load_weight_entries,
        medication_history_path,
        metrics_db_path,
        next_appointment_path,
        now_utc,
        parse_value,
        patterns_path,
        profile_path,
        reconciliation_path,
        record_vital,
        record_weight,
        review_queue_path,
        review_worklist_path,
        save_conflicts,
        save_profile,
        save_review_queue,
        set_nested_field,
        slugify,
        summary_path,
        sync_conflict_count,
        this_week_path,
        timeline_path,
        today_path,
        trends_path,
        upsert_record,
        vitals_trends_path,
        weight_trends_path,
        workspace_lock,
        write_assistant_update,
        add_note,
        archive_old_records,
        find_cached_dashboard,
        record_intent_usage,
        save_dashboard_to_cache,
        log_extraction_event,
        compute_extraction_stats,
        render_extraction_accuracy_text,
        extraction_accuracy_path,
    )
    from .extraction import (
        ingest_document,
        process_inbox,
    )
    from .rendering import (
        build_timeline_events,
        create_backup_archive,
        refresh_views,
        render_calendar_ics,
        render_care_status_text,
        render_change_report_text,
        render_clinician_packet_text,
        render_dossier_text,
        render_health_home_text,
        render_intake_summary_text,
        render_medication_reconciliation_text,
        render_next_appointment_text,
        render_patterns_text,
        render_portal_message_text,
        render_redacted_summary_text,
        render_review_worklist_text,
        render_start_here_text,
        render_summary_text,
        render_this_week_text,
        render_timeline_text,
        render_today_text,
        render_trends_text,
        render_vitals_trends_text,
        render_weight_trends_text,
        render_appointment_request_text,
        render_query_dashboard,
        classify_query_intent,
    )
except ImportError:
    from care_workspace import (
        DEFAULT_PROFILE,
        RECORD_KEYS,
        atomic_write_text,
        calendar_export_path,
        care_status_path,
        change_report_path,
        conflicts_path,
        dossier_path,
        ensure_person,
        exports_dir,
        home_path,
        intake_summary_path,
        load_conflicts,
        load_medication_history,
        load_profile,
        load_review_queue,
        list_inbox_files,
        load_vital_entries,
        load_weight_entries,
        medication_history_path,
        metrics_db_path,
        next_appointment_path,
        now_utc,
        parse_value,
        patterns_path,
        profile_path,
        reconciliation_path,
        record_vital,
        record_weight,
        review_queue_path,
        review_worklist_path,
        save_conflicts,
        save_profile,
        save_review_queue,
        set_nested_field,
        slugify,
        summary_path,
        sync_conflict_count,
        this_week_path,
        timeline_path,
        today_path,
        trends_path,
        upsert_record,
        vitals_trends_path,
        weight_trends_path,
        workspace_lock,
        write_assistant_update,
        add_note,
        archive_old_records,
        find_cached_dashboard,
        record_intent_usage,
        save_dashboard_to_cache,
        log_extraction_event,
        compute_extraction_stats,
        render_extraction_accuracy_text,
        extraction_accuracy_path,
    )
    from extraction import (
        ingest_document,
        process_inbox,
    )
    from rendering import (
        build_timeline_events,
        create_backup_archive,
        refresh_views,
        render_calendar_ics,
        render_care_status_text,
        render_change_report_text,
        render_clinician_packet_text,
        render_dossier_text,
        render_health_home_text,
        render_intake_summary_text,
        render_medication_reconciliation_text,
        render_next_appointment_text,
        render_patterns_text,
        render_portal_message_text,
        render_redacted_summary_text,
        render_review_worklist_text,
        render_start_here_text,
        render_summary_text,
        render_this_week_text,
        render_timeline_text,
        render_today_text,
        render_trends_text,
        render_vitals_trends_text,
        render_weight_trends_text,
        render_appointment_request_text,
        render_query_dashboard,
    )


def command_init_project(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, ""):
        directory = ensure_person(
            root,
            "",
            args.name,
            args.date_of_birth,
            args.sex,
        )
        summary, dossier = refresh_views(root, "")
        write_assistant_update(
            root,
            "",
            "I initialized the Health Skill workspace.",
            [
                "The project folder now has the core structured files.",
                "HEALTH_HOME.md and TODAY.md are ready as the main starting points.",
                "You can drop new files into inbox/ whenever you want me to ingest them.",
            ],
        )
    print(directory)
    print(summary)
    print(dossier)
    return 0


def command_create_person(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        directory = ensure_person(
            root,
            args.person_id,
            args.name,
            args.date_of_birth,
            args.sex,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            f"I created the workspace for {args.name or args.person_id}.",
            [
                "The main project files are in place.",
                "The record is ready for inbox processing, notes, and appointment prep.",
            ],
        )
    print(directory)
    return 0


def command_update_profile(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        set_nested_field(profile, args.field, parse_value(args.value))
        sync_conflict_count(root, args.person_id, profile)
        path = save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I updated the profile.",
            [
                f"Field updated: {args.field}.",
                "I refreshed the user-facing views so the change is visible everywhere.",
            ],
        )
    print(path)
    return 0


def command_upsert_record(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path, _ = upsert_record(
            root,
            args.person_id,
            args.section,
            parse_value(args.value),
            args.source_type,
            args.source_label,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            f"I updated the {args.section} record.",
            [
                "The structured profile was refreshed.",
                "The dossier and day-to-day views were regenerated.",
            ],
        )
    print(path)
    return 0


def command_add_note(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        note_path = add_note(
            root,
            args.person_id,
            args.title,
            args.body,
            args.source_type,
            args.source_label,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I added a dated note.",
            [
                f"Note title: {args.title}.",
                "The timeline and current views were refreshed.",
            ],
        )
    print(note_path)
    return 0


def command_ingest_document(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        destination_path, note_path = ingest_document(
            root,
            args.person_id,
            Path(args.path),
            args.doc_type,
            args.title,
            args.source_date,
        )
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I ingested a document into the workspace.",
            [
                f"Archived file: {destination_path.name}.",
                "The structured record and review queue were refreshed.",
                "Any extracted facts were logged with visible trust labels.",
            ],
        )
    print(destination_path)
    print(note_path)
    return 0


def command_process_inbox(args: argparse.Namespace) -> int:
    root = Path(args.root)
    dry_run = getattr(args, "dry_run", False)
    with workspace_lock(root, args.person_id):
        before_ids = {item["id"] for item in load_review_queue(root, args.person_id)}
        page_limit = getattr(args, "page_limit", 10)
        processed = process_inbox(root, args.person_id, dry_run=dry_run, page_limit=page_limit)
        if dry_run:
            return 0
        refresh_views(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        new_review_items = [item for item in review_queue if item["id"] not in before_ids]
        atomic_write_text(
            intake_summary_path(root, args.person_id),
            render_intake_summary_text(processed, new_review_items),
        )
        write_assistant_update(
            root,
            args.person_id,
            "I finished processing the inbox.",
            [
                f"Files processed: {len(processed)}.",
                f"Possible updates found: {len(new_review_items)}.",
                "The originals were moved into Archive/ and the workspace views were refreshed.",
            ],
        )
    for archived_path, note_path in processed:
        print(archived_path)
        print(note_path)
    print(intake_summary_path(root, args.person_id))
    return 0


def command_list_review_queue(args: argparse.Namespace) -> int:
    items = load_review_queue(Path(args.root), args.person_id)
    if args.status:
        items = [item for item in items if item.get("status") == args.status]
    print(json.dumps(items, indent=2))
    return 0


def command_resolve_review_item(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        updated = False
        for item in items:
            if item["id"] == args.review_id:
                item["status"] = args.status
                item["resolution_note"] = args.note or ""
                item["resolved_at"] = now_utc()
                log_extraction_event(
                    root, args.person_id,
                    event_type=args.status,
                    section=item.get("section", ""),
                    candidate=item.get("candidate", {}),
                    confidence=item.get("confidence", ""),
                    tier=item.get("tier", ""),
                    source_title=item.get("source_title", ""),
                    review_id=args.review_id,
                    resolution=args.status,
                    note=args.note or "",
                )
                updated = True
                break
        if not updated:
            raise SystemExit(f"Review item not found: {args.review_id}")
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I resolved a review item.",
            [
                f"Review item: {args.review_id}.",
                f"Decision: {args.status}.",
            ],
        )
    print(review_queue_path(root, args.person_id))
    return 0


def command_apply_review_item(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        target = None
        for item in items:
            if item["id"] == args.review_id:
                target = item
                break
        if target is None:
            raise SystemExit(f"Review item not found: {args.review_id}")
        upsert_record(
            root,
            args.person_id,
            target["section"],
            target["candidate"],
            source_type="review-application",
            source_label=target.get("source_title", ""),
            source_date=target.get("source_date", ""),
        )
        target["applied"] = True
        target["status"] = "applied"
        target["applied_at"] = now_utc()
        log_extraction_event(
            root, args.person_id,
            event_type="applied",
            section=target.get("section", ""),
            candidate=target.get("candidate", {}),
            confidence=target.get("confidence", ""),
            tier=target.get("tier", ""),
            source_title=target.get("source_title", ""),
            review_id=args.review_id,
            resolution="applied",
        )
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I applied a reviewed item into the structured record.",
            [
                f"Review item: {args.review_id}.",
                "The dossier and quick views now reflect that accepted fact.",
            ],
        )
    print(review_queue_path(root, args.person_id))
    return 0


def command_apply_review_tier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        changed = 0
        for item in items:
            if item.get("status") != "open" or item.get("tier") != args.tier or item.get("applied"):
                continue
            upsert_record(
                root,
                args.person_id,
                item["section"],
                item["candidate"],
                source_type="review-application",
                source_label=item.get("source_title", ""),
                source_date=item.get("source_date", ""),
            )
            item["applied"] = True
            item["status"] = "applied"
            item["applied_at"] = now_utc()
            log_extraction_event(
                root, args.person_id, event_type="applied",
                section=item.get("section", ""), candidate=item.get("candidate", {}),
                confidence=item.get("confidence", ""), tier=item.get("tier", ""),
                source_title=item.get("source_title", ""), review_id=item.get("id", ""),
                resolution="applied",
            )
            changed += 1
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I batch-applied review items.",
            [
                f"Tier: {args.tier}.",
                f"Items applied: {changed}.",
            ],
        )
    print(f"Applied {changed} review items")
    return 0


def command_resolve_review_tier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        items = load_review_queue(root, args.person_id)
        changed = 0
        for item in items:
            if item.get("status") != "open" or item.get("tier") != args.tier:
                continue
            item["status"] = args.status
            item["resolution_note"] = args.note or ""
            item["resolved_at"] = now_utc()
            log_extraction_event(
                root, args.person_id, event_type=args.status,
                section=item.get("section", ""), candidate=item.get("candidate", {}),
                confidence=item.get("confidence", ""), tier=item.get("tier", ""),
                source_title=item.get("source_title", ""), review_id=item.get("id", ""),
                resolution=args.status, note=args.note or "",
            )
            changed += 1
        save_review_queue(root, args.person_id, items)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I batch-resolved review items.",
            [
                f"Tier: {args.tier}.",
                f"Decision: {args.status}.",
                f"Items resolved: {changed}.",
            ],
        )
    print(f"Resolved {changed} review items")
    return 0


def command_render_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path, _ = refresh_views(root, args.person_id)
    print(path)
    return 0


def command_render_dossier(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        _, path = refresh_views(root, args.person_id)
    print(path)
    return 0


def command_render_home(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(home_path(root, args.person_id))
    return 0


def command_render_today(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(today_path(root, args.person_id))
    return 0


def command_render_this_week(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(this_week_path(root, args.person_id))
    return 0


def command_render_next_appointment(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(next_appointment_path(root, args.person_id))
    return 0


def command_render_patterns(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(patterns_path(root, args.person_id))
    return 0


def command_render_review_worklist(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(review_worklist_path(root, args.person_id))
    return 0


def command_render_care_status(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        refresh_views(root, args.person_id)
    print(care_status_path(root, args.person_id))
    return 0


def command_render_intake_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        if not intake_summary_path(root, args.person_id).exists():
            atomic_write_text(
                intake_summary_path(root, args.person_id),
                render_intake_summary_text([], []),
            )
    print(intake_summary_path(root, args.person_id))
    return 0


def command_render_timeline(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        weight_entries = load_weight_entries(root, args.person_id)
        vital_entries = load_vital_entries(root, args.person_id)
        atomic_write_text(
            timeline_path(root, args.person_id),
            render_timeline_text(
                build_timeline_events(root, args.person_id, profile, medication_history, weight_entries, vital_entries)
            ),
        )
    print(timeline_path(root, args.person_id))
    return 0


def command_render_change_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        conflicts = load_conflicts(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        weight_entries = load_weight_entries(root, args.person_id)
        vital_entries = load_vital_entries(root, args.person_id)
        atomic_write_text(
            change_report_path(root, args.person_id),
            render_change_report_text(
                profile,
                conflicts,
                review_queue,
                medication_history,
                weight_entries,
                vital_entries,
                args.days,
            ),
        )
    print(change_report_path(root, args.person_id))
    return 0


def command_render_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        atomic_write_text(trends_path(root, args.person_id), render_trends_text(profile))
    print(trends_path(root, args.person_id))
    return 0


def command_record_weight(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entry_date = args.date or date.today().isoformat()
        record_weight(root, args.person_id, entry_date, args.value, args.unit, args.note)
        record_vital(root, args.person_id, entry_date, "weight", str(args.value), args.unit, args.note)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I recorded a new weight entry.",
            [
                f"Entry: {args.value} {args.unit} on {entry_date}.",
                "Weight and vital trend views were refreshed.",
            ],
        )
    print(metrics_db_path(root, args.person_id))
    return 0


def command_record_vital(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entry_date = args.date or date.today().isoformat()
        record_vital(root, args.person_id, entry_date, args.metric, args.value, args.unit, args.note)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I recorded a non-weight health metric.",
            [
                f"Metric: {args.metric}.",
                f"Value: {args.value}{(' ' + args.unit) if args.unit else ''}.",
                "The vitals trend view was refreshed.",
            ],
        )
    print(metrics_db_path(root, args.person_id))
    return 0


def command_render_weight_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entries = load_weight_entries(root, args.person_id)
        atomic_write_text(weight_trends_path(root, args.person_id), render_weight_trends_text(entries))
        refresh_views(root, args.person_id)
    print(weight_trends_path(root, args.person_id))
    return 0


def command_render_vitals_trends(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        entries = load_vital_entries(root, args.person_id)
        atomic_write_text(vitals_trends_path(root, args.person_id), render_vitals_trends_text(entries))
        refresh_views(root, args.person_id)
    print(vitals_trends_path(root, args.person_id))
    return 0


def command_reconcile_medications(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        conflicts = load_conflicts(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        atomic_write_text(
            reconciliation_path(root, args.person_id),
            render_medication_reconciliation_text(profile, conflicts, review_queue, medication_history),
        )
    print(reconciliation_path(root, args.person_id))
    return 0


def command_export_calendar(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        atomic_write_text(calendar_export_path(root, args.person_id), render_calendar_ics(profile))
    print(calendar_export_path(root, args.person_id))
    return 0


def command_export_redacted_summary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / "redacted_summary.md"
        atomic_write_text(path, render_redacted_summary_text(profile))
        write_assistant_update(
            root,
            args.person_id,
            "I created a redacted shareable summary.",
            [
                "Direct identifiers were reduced.",
                "The export keeps only the essentials for sharing.",
            ],
        )
    print(path)
    return 0


def command_export_clinician_packet(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / f"clinician_packet_{slugify(args.visit_type)}.md"
        atomic_write_text(path, render_clinician_packet_text(profile, args.visit_type, args.reason))
        write_assistant_update(
            root,
            args.person_id,
            "I created a clinician packet.",
            [
                f"Visit type: {args.visit_type}.",
                "It keeps the focus on what a clinician is most likely to need quickly.",
            ],
        )
    print(path)
    return 0


def command_export_portal_message(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        path = exports_dir(root, args.person_id) / "portal_message_draft.md"
        atomic_write_text(path, render_portal_message_text(profile, args.goal))
        write_assistant_update(
            root,
            args.person_id,
            "I drafted a short portal message.",
            [
                "The message is based on the current record and recent changes.",
                "It is ready to edit before sending.",
            ],
        )
    print(path)
    return 0


def command_generate_appointment_request(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        filename = f"appointment_request_{slugify(args.specialty)}.md"
        path = exports_dir(root, args.person_id) / filename
        atomic_write_text(
            path,
            render_appointment_request_text(
                profile,
                args.specialty,
                args.reason,
                args.visit_type,
            ),
        )
        write_assistant_update(
            root,
            args.person_id,
            "I created an appointment request draft.",
            [
                f"Specialty: {args.specialty}.",
                "This draft is ready for a booking form or provider portal.",
            ],
        )
    print(path)
    return 0


def command_list_conflicts(args: argparse.Namespace) -> int:
    conflicts = load_conflicts(Path(args.root), args.person_id)
    if args.status:
        conflicts = [item for item in conflicts if item["status"] == args.status]
    print(json.dumps(conflicts, indent=2))
    return 0


def command_resolve_conflict(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        conflicts = load_conflicts(root, args.person_id)
        updated = False
        for item in conflicts:
            if item["id"] == args.conflict_id:
                item["status"] = "resolved"
                item["resolution"] = args.resolution
                item["resolution_note"] = args.note or ""
                item["resolved_at"] = now_utc()
                updated = True
                break
        if not updated:
            raise SystemExit(f"Conflict not found: {args.conflict_id}")
        save_conflicts(root, args.person_id, conflicts)
        profile = load_profile(root, args.person_id)
        sync_conflict_count(root, args.person_id, profile)
        save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I resolved a source conflict.",
            [
                f"Conflict: {args.conflict_id}.",
                f"Resolution: {args.resolution}.",
            ],
        )
    print(conflicts_path(root, args.person_id))
    return 0


def command_set_preference(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        profile = load_profile(root, args.person_id)
        preferences = profile.setdefault("preferences", deepcopy(DEFAULT_PROFILE["preferences"]))
        preferences[args.key] = parse_value(args.value)
        save_profile(root, args.person_id, profile)
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I updated a workspace preference.",
            [
                f"Preference: {args.key}.",
                "The user-facing files now reflect that preference.",
            ],
        )
    print(profile_path(root, args.person_id))
    return 0


def command_backup_project(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        path = create_backup_archive(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I created a workspace backup archive.",
            [
                f"Backup file: {path.name}.",
                "This is useful before major edits or when you want a portable copy.",
            ],
        )
    print(path)
    return 0


def command_query_dashboard(args: argparse.Namespace) -> int:
    root = Path(args.root)
    no_cache = getattr(args, "no_cache", False)
    save = getattr(args, "save", False)

    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        intent = classify_query_intent(args.query)

        # Check cache first (unless --no-cache)
        if not no_cache:
            cached = find_cached_dashboard(root, args.person_id, args.query, intent)
            if cached:
                dashboard_text = cached["dashboard_text"]
                # Prepend cache notice
                header = (
                    f"> Reusing saved dashboard from "
                    f"{cached.get('cached_at', 'unknown')[:10]} "
                    f"(original query: \"{cached.get('query', '')}\")\n\n"
                )
                dashboard_text = header + dashboard_text
                output_path = exports_dir(root, args.person_id) / "QUERY_DASHBOARD.md"
                atomic_write_text(output_path, dashboard_text)
                record_intent_usage(root, args.person_id, intent)
                print(f"[cache-hit] Reused dashboard for: {cached.get('query', '')}")
                print(output_path)
                return 0

        # Generate fresh dashboard
        profile = load_profile(root, args.person_id)
        conflicts = load_conflicts(root, args.person_id)
        review_queue = load_review_queue(root, args.person_id)
        medication_history = load_medication_history(root, args.person_id)
        weight_entries = load_weight_entries(root, args.person_id)
        vital_entries = load_vital_entries(root, args.person_id)
        inbox_files = list_inbox_files(root, args.person_id)
        result = render_query_dashboard(
            query=args.query,
            profile=profile,
            conflicts=conflicts,
            review_queue=review_queue,
            medication_history=medication_history,
            weight_entries=weight_entries,
            vital_entries=vital_entries,
            inbox_files=inbox_files,
        )
        output_path = exports_dir(root, args.person_id) / "QUERY_DASHBOARD.md"
        atomic_write_text(output_path, result.text)
        record_intent_usage(root, args.person_id, intent)

        # Generate HTML artifact alongside markdown
        try:
            from .artifacts import generate_query_dashboard_artifact
        except ImportError:
            try:
                from artifacts import generate_query_dashboard_artifact
            except ImportError:
                generate_query_dashboard_artifact = None  # type: ignore[assignment]
        if generate_query_dashboard_artifact is not None:
            try:
                html_path = generate_query_dashboard_artifact(root, args.person_id, args.query)
                print(html_path)
            except Exception:
                pass

        if save:
            save_dashboard_to_cache(
                root, args.person_id,
                args.query, result.primary_intent, result.intents_used,
                result.text,
            )
            print(f"[saved] Dashboard cached for reuse (intent: {result.primary_intent})")

    print(output_path)
    return 0


def command_archive_old_records(args: argparse.Namespace) -> int:
    root = Path(args.root)
    with workspace_lock(root, args.person_id):
        ensure_person(root, args.person_id)
        try:
            archive_path = archive_old_records(root, args.person_id, args.max_age_months)
        except ImportError:
            print("Error: python-dateutil is required for archival. Install with: pip install python-dateutil")
            return 1
        refresh_views(root, args.person_id)
        write_assistant_update(
            root,
            args.person_id,
            "I archived old records to keep the active profile focused.",
            [
                f"Archive file: {archive_path.name}.",
                f"Records older than {args.max_age_months} months were moved.",
                "The active profile now contains only recent data. Historical trends are preserved in the archive.",
            ],
        )
    print(archive_path)
    return 0


def command_extraction_audit(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_person(root, args.person_id)
    stats = compute_extraction_stats(root, args.person_id)
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        report = render_extraction_accuracy_text(stats)
        output_path = extraction_accuracy_path(root, args.person_id)
        atomic_write_text(output_path, report)
        print(report)
        print(f"\nSaved to: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Health Skill workspace helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = subparsers.add_parser("init-project")
    init_project.add_argument("--root", required=True)
    init_project.add_argument("--name", default="")
    init_project.add_argument("--date-of-birth", default="")
    init_project.add_argument("--sex", default="")
    init_project.set_defaults(func=command_init_project)

    create_person = subparsers.add_parser("create-person")
    create_person.add_argument("--root", required=True)
    create_person.add_argument("--person-id", required=True)
    create_person.add_argument("--name", default="")
    create_person.add_argument("--date-of-birth", default="")
    create_person.add_argument("--sex", default="")
    create_person.set_defaults(func=command_create_person)

    update_profile = subparsers.add_parser("update-profile")
    update_profile.add_argument("--root", required=True)
    update_profile.add_argument("--person-id", default="")
    update_profile.add_argument("--field", required=True)
    update_profile.add_argument("--value", required=True)
    update_profile.set_defaults(func=command_update_profile)

    upsert = subparsers.add_parser("upsert-record")
    upsert.add_argument("--root", required=True)
    upsert.add_argument("--person-id", default="")
    upsert.add_argument("--section", choices=sorted(RECORD_KEYS), required=True)
    upsert.add_argument("--value", required=True)
    upsert.add_argument("--source-type", default="user")
    upsert.add_argument("--source-label", default="")
    upsert.add_argument("--source-date", default="")
    upsert.set_defaults(func=command_upsert_record)

    add_note_parser = subparsers.add_parser("add-note")
    add_note_parser.add_argument("--root", required=True)
    add_note_parser.add_argument("--person-id", default="")
    add_note_parser.add_argument("--title", required=True)
    add_note_parser.add_argument("--body", required=True)
    add_note_parser.add_argument("--source-type", default="user")
    add_note_parser.add_argument("--source-label", default="")
    add_note_parser.add_argument("--source-date", default="")
    add_note_parser.set_defaults(func=command_add_note)

    ingest = subparsers.add_parser("ingest-document")
    ingest.add_argument("--root", required=True)
    ingest.add_argument("--person-id", default="")
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--doc-type", required=True)
    ingest.add_argument("--title", default="")
    ingest.add_argument("--source-date", default="")
    ingest.set_defaults(func=command_ingest_document)

    process_inbox_parser = subparsers.add_parser("process-inbox")
    process_inbox_parser.add_argument("--root", required=True)
    process_inbox_parser.add_argument("--person-id", default="")
    process_inbox_parser.add_argument("--dry-run", action="store_true", help="Preview inbox processing without moving files")
    process_inbox_parser.add_argument("--page-limit", type=int, default=10, help="Max PDF pages to read (default: 10)")
    process_inbox_parser.set_defaults(func=command_process_inbox)

    list_review_queue = subparsers.add_parser("list-review-queue")
    list_review_queue.add_argument("--root", required=True)
    list_review_queue.add_argument("--person-id", default="")
    list_review_queue.add_argument(
        "--status",
        choices=["open", "applied", "accepted", "rejected"],
        default="",
    )
    list_review_queue.set_defaults(func=command_list_review_queue)

    resolve_review = subparsers.add_parser("resolve-review-item")
    resolve_review.add_argument("--root", required=True)
    resolve_review.add_argument("--person-id", default="")
    resolve_review.add_argument("--review-id", required=True)
    resolve_review.add_argument(
        "--status",
        choices=["accepted", "rejected"],
        required=True,
    )
    resolve_review.add_argument("--note", default="")
    resolve_review.set_defaults(func=command_resolve_review_item)

    apply_review = subparsers.add_parser("apply-review-item")
    apply_review.add_argument("--root", required=True)
    apply_review.add_argument("--person-id", default="")
    apply_review.add_argument("--review-id", required=True)
    apply_review.set_defaults(func=command_apply_review_item)

    apply_review_tier = subparsers.add_parser("apply-review-tier")
    apply_review_tier.add_argument("--root", required=True)
    apply_review_tier.add_argument("--person-id", default="")
    apply_review_tier.add_argument(
        "--tier",
        choices=[
            "safe_to_auto_apply",
            "needs_quick_confirmation",
            "do_not_trust_without_human_review",
        ],
        required=True,
    )
    apply_review_tier.set_defaults(func=command_apply_review_tier)

    resolve_review_tier = subparsers.add_parser("resolve-review-tier")
    resolve_review_tier.add_argument("--root", required=True)
    resolve_review_tier.add_argument("--person-id", default="")
    resolve_review_tier.add_argument(
        "--tier",
        choices=[
            "safe_to_auto_apply",
            "needs_quick_confirmation",
            "do_not_trust_without_human_review",
        ],
        required=True,
    )
    resolve_review_tier.add_argument("--status", choices=["accepted", "rejected"], required=True)
    resolve_review_tier.add_argument("--note", default="")
    resolve_review_tier.set_defaults(func=command_resolve_review_tier)

    render_summary = subparsers.add_parser("render-summary")
    render_summary.add_argument("--root", required=True)
    render_summary.add_argument("--person-id", default="")
    render_summary.set_defaults(func=command_render_summary)

    render_dossier = subparsers.add_parser("render-dossier")
    render_dossier.add_argument("--root", required=True)
    render_dossier.add_argument("--person-id", default="")
    render_dossier.set_defaults(func=command_render_dossier)

    render_home = subparsers.add_parser("render-home")
    render_home.add_argument("--root", required=True)
    render_home.add_argument("--person-id", default="")
    render_home.set_defaults(func=command_render_home)

    render_today = subparsers.add_parser("render-today")
    render_today.add_argument("--root", required=True)
    render_today.add_argument("--person-id", default="")
    render_today.set_defaults(func=command_render_today)

    render_this_week = subparsers.add_parser("render-this-week")
    render_this_week.add_argument("--root", required=True)
    render_this_week.add_argument("--person-id", default="")
    render_this_week.set_defaults(func=command_render_this_week)

    render_next_appointment = subparsers.add_parser("render-next-appointment")
    render_next_appointment.add_argument("--root", required=True)
    render_next_appointment.add_argument("--person-id", default="")
    render_next_appointment.set_defaults(func=command_render_next_appointment)

    render_patterns = subparsers.add_parser("render-patterns")
    render_patterns.add_argument("--root", required=True)
    render_patterns.add_argument("--person-id", default="")
    render_patterns.set_defaults(func=command_render_patterns)

    render_review_worklist = subparsers.add_parser("render-review-worklist")
    render_review_worklist.add_argument("--root", required=True)
    render_review_worklist.add_argument("--person-id", default="")
    render_review_worklist.set_defaults(func=command_render_review_worklist)

    render_care_status = subparsers.add_parser("render-care-status")
    render_care_status.add_argument("--root", required=True)
    render_care_status.add_argument("--person-id", default="")
    render_care_status.set_defaults(func=command_render_care_status)

    render_intake_summary = subparsers.add_parser("render-intake-summary")
    render_intake_summary.add_argument("--root", required=True)
    render_intake_summary.add_argument("--person-id", default="")
    render_intake_summary.set_defaults(func=command_render_intake_summary)

    render_timeline = subparsers.add_parser("render-timeline")
    render_timeline.add_argument("--root", required=True)
    render_timeline.add_argument("--person-id", default="")
    render_timeline.set_defaults(func=command_render_timeline)

    render_change_report = subparsers.add_parser("render-change-report")
    render_change_report.add_argument("--root", required=True)
    render_change_report.add_argument("--person-id", default="")
    render_change_report.add_argument("--days", type=int, default=30)
    render_change_report.set_defaults(func=command_render_change_report)

    render_trends = subparsers.add_parser("render-trends")
    render_trends.add_argument("--root", required=True)
    render_trends.add_argument("--person-id", default="")
    render_trends.set_defaults(func=command_render_trends)

    record_weight_parser = subparsers.add_parser("record-weight")
    record_weight_parser.add_argument("--root", required=True)
    record_weight_parser.add_argument("--person-id", default="")
    record_weight_parser.add_argument("--value", type=float, required=True)
    record_weight_parser.add_argument("--unit", default="kg")
    record_weight_parser.add_argument("--date", default="")
    record_weight_parser.add_argument("--note", default="")
    record_weight_parser.set_defaults(func=command_record_weight)

    render_weight_trends = subparsers.add_parser("render-weight-trends")
    render_weight_trends.add_argument("--root", required=True)
    render_weight_trends.add_argument("--person-id", default="")
    render_weight_trends.set_defaults(func=command_render_weight_trends)

    record_vital_parser = subparsers.add_parser("record-vital")
    record_vital_parser.add_argument("--root", required=True)
    record_vital_parser.add_argument("--person-id", default="")
    record_vital_parser.add_argument(
        "--metric",
        choices=[
            "blood_pressure",
            "glucose",
            "heart_rate",
            "oxygen_saturation",
            "sleep_hours",
            "symptom_score",
            "adherence",
            "pain_score",
            "mood_score",
            "weight",
        ],
        required=True,
    )
    record_vital_parser.add_argument("--value", required=True)
    record_vital_parser.add_argument("--unit", default="")
    record_vital_parser.add_argument("--date", default="")
    record_vital_parser.add_argument("--note", default="")
    record_vital_parser.set_defaults(func=command_record_vital)

    render_vitals_trends = subparsers.add_parser("render-vitals-trends")
    render_vitals_trends.add_argument("--root", required=True)
    render_vitals_trends.add_argument("--person-id", default="")
    render_vitals_trends.set_defaults(func=command_render_vitals_trends)

    reconcile = subparsers.add_parser("reconcile-medications")
    reconcile.add_argument("--root", required=True)
    reconcile.add_argument("--person-id", default="")
    reconcile.set_defaults(func=command_reconcile_medications)

    export_calendar = subparsers.add_parser("export-calendar")
    export_calendar.add_argument("--root", required=True)
    export_calendar.add_argument("--person-id", default="")
    export_calendar.set_defaults(func=command_export_calendar)

    export_redacted = subparsers.add_parser("export-redacted-summary")
    export_redacted.add_argument("--root", required=True)
    export_redacted.add_argument("--person-id", default="")
    export_redacted.set_defaults(func=command_export_redacted_summary)

    export_clinician_packet = subparsers.add_parser("export-clinician-packet")
    export_clinician_packet.add_argument("--root", required=True)
    export_clinician_packet.add_argument("--person-id", default="")
    export_clinician_packet.add_argument("--visit-type", default="specialist")
    export_clinician_packet.add_argument("--reason", required=True)
    export_clinician_packet.set_defaults(func=command_export_clinician_packet)

    export_portal_message = subparsers.add_parser("export-portal-message")
    export_portal_message.add_argument("--root", required=True)
    export_portal_message.add_argument("--person-id", default="")
    export_portal_message.add_argument("--goal", required=True)
    export_portal_message.set_defaults(func=command_export_portal_message)

    appointment_request = subparsers.add_parser("generate-appointment-request")
    appointment_request.add_argument("--root", required=True)
    appointment_request.add_argument("--person-id", default="")
    appointment_request.add_argument("--specialty", required=True)
    appointment_request.add_argument("--reason", required=True)
    appointment_request.add_argument("--visit-type", default="specialist")
    appointment_request.set_defaults(func=command_generate_appointment_request)

    list_conflicts = subparsers.add_parser("list-conflicts")
    list_conflicts.add_argument("--root", required=True)
    list_conflicts.add_argument("--person-id", default="")
    list_conflicts.add_argument("--status", choices=["open", "resolved"], default="")
    list_conflicts.set_defaults(func=command_list_conflicts)

    resolve = subparsers.add_parser("resolve-conflict")
    resolve.add_argument("--root", required=True)
    resolve.add_argument("--person-id", default="")
    resolve.add_argument("--conflict-id", required=True)
    resolve.add_argument("--resolution", choices=["keep-current", "accept-new"], required=True)
    resolve.add_argument("--note", default="")
    resolve.set_defaults(func=command_resolve_conflict)

    set_preference = subparsers.add_parser("set-preference")
    set_preference.add_argument("--root", required=True)
    set_preference.add_argument("--person-id", default="")
    set_preference.add_argument(
        "--key",
        choices=[
            "summary_style",
            "weight_unit",
            "primary_caregiver",
            "appointment_prep_style",
            "communication_tone",
            "preferred_clinicians",
        ],
        required=True,
    )
    set_preference.add_argument("--value", required=True)
    set_preference.set_defaults(func=command_set_preference)

    backup_project = subparsers.add_parser("backup-project")
    backup_project.add_argument("--root", required=True)
    backup_project.add_argument("--person-id", default="")
    backup_project.set_defaults(func=command_backup_project)

    query_dashboard = subparsers.add_parser("query-dashboard")
    query_dashboard.add_argument("--root", required=True)
    query_dashboard.add_argument("--person-id", default="")
    query_dashboard.add_argument("--query", required=True, help="Natural-language question to focus the dashboard on")
    query_dashboard.add_argument("--save", action="store_true", help="Save this dashboard for reuse on similar queries")
    query_dashboard.add_argument("--no-cache", action="store_true", help="Skip cache lookup, always generate fresh")
    query_dashboard.set_defaults(func=command_query_dashboard)

    archive_old = subparsers.add_parser("archive-old-records")
    archive_old.add_argument("--root", required=True)
    archive_old.add_argument("--person-id", default="")
    archive_old.add_argument("--max-age-months", type=int, default=12, help="Archive records older than N months (default: 12)")
    archive_old.set_defaults(func=command_archive_old_records)

    extraction_audit = subparsers.add_parser("extraction-audit")
    extraction_audit.add_argument("--root", required=True)
    extraction_audit.add_argument("--person-id", default="")
    extraction_audit.add_argument("--json", action="store_true", help="Output raw JSON stats instead of markdown")
    extraction_audit.set_defaults(func=command_extraction_audit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
