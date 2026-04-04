import argparse
import tempfile
import unittest
from pathlib import Path

from scripts.caregiver_dashboard import build_caregiver_handoff, build_dashboard
from scripts.care_workspace import (
    add_note,
    assistant_update_path,
    archive_dir,
    calendar_export_path,
    care_status_path,
    change_report_path,
    dossier_path,
    home_path,
    ensure_person,
    ingest_document,
    inbox_dir,
    intake_summary_path,
    load_vital_entries,
    next_appointment_path,
    patterns_path,
    load_conflicts,
    load_medication_history,
    load_profile,
    load_review_queue,
    load_weight_entries,
    process_inbox,
    reconciliation_path,
    render_clinician_packet_text,
    render_portal_message_text,
    render_redacted_summary_text,
    record_weight,
    record_vital,
    refresh_views,
    render_change_report_text,
    render_dossier_text,
    render_summary_text,
    render_timeline_text,
    save_profile,
    summary_path,
    timeline_path,
    trends_path,
    upsert_record,
    render_calendar_ics,
    render_trends_text,
    review_worklist_path,
    build_timeline_events,
    command_process_inbox,
    start_here_path,
    this_week_path,
    today_path,
    vitals_trends_path,
)
from scripts.clinician_handoff import build_handoff


class CareWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ensure_person_creates_expected_files(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe")
        self.assertTrue((self.root / "people" / "jane-doe" / "profile.json").exists())
        self.assertTrue((self.root / "people" / "jane-doe" / "summary.md").exists())
        self.assertTrue((self.root / "people" / "jane-doe" / "conflicts.json").exists())
        self.assertTrue((self.root / "people" / "jane-doe" / "inbox").exists())
        self.assertTrue((self.root / "people" / "jane-doe" / "Archive").exists())
        self.assertTrue((self.root / "people" / "jane-doe" / "exports").exists())

    def test_profile_migrates_legacy_lists_to_records(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe")
        profile = load_profile(self.root, "jane-doe")
        profile["conditions"] = ["Asthma"]
        save_profile(self.root, "jane-doe", profile)

        reloaded = load_profile(self.root, "jane-doe")
        self.assertEqual(reloaded["conditions"][0]["name"], "Asthma")
        self.assertEqual(reloaded["schema_version"], 4)

    def test_project_root_mode_creates_explicit_health_files(self) -> None:
        ensure_person(self.root, "", "Jane Doe", "1980-01-01", "female")
        refresh_views(self.root, "")

        self.assertTrue((self.root / "HEALTH_PROFILE.json").exists())
        self.assertTrue((self.root / "HEALTH_HOME.md").exists())
        self.assertTrue((self.root / "HEALTH_PATTERNS.md").exists())
        self.assertTrue((self.root / "HEALTH_SUMMARY.md").exists())
        self.assertTrue((self.root / "HEALTH_DOSSIER.md").exists())
        self.assertTrue((self.root / "HEALTH_CONFLICTS.json").exists())
        self.assertTrue((self.root / "INTAKE_SUMMARY.md").exists())
        self.assertTrue((self.root / "ASSISTANT_UPDATE.md").exists())
        self.assertTrue((self.root / "START_HERE.md").exists())
        self.assertTrue((self.root / "TODAY.md").exists())
        self.assertTrue((self.root / "THIS_WEEK.md").exists())
        self.assertTrue((self.root / "NEXT_APPOINTMENT.md").exists())
        self.assertTrue((self.root / "REVIEW_WORKLIST.md").exists())
        self.assertTrue((self.root / "CARE_STATUS.md").exists())
        self.assertTrue((self.root / "VITALS_TRENDS.md").exists())
        self.assertTrue((self.root / "inbox").exists())
        self.assertTrue((self.root / "Archive").exists())
        self.assertTrue((self.root / "notes").exists())

    def test_upsert_record_detects_conflicts(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe")
        upsert_record(
            self.root,
            "jane-doe",
            "medications",
            {"name": "atorvastatin", "dose": "10 mg nightly"},
            source_label="initial med list",
        )
        upsert_record(
            self.root,
            "jane-doe",
            "medications",
            {"name": "atorvastatin", "dose": "20 mg nightly"},
            source_type="document",
            source_label="outside clinic note",
        )
        conflicts = load_conflicts(self.root, "jane-doe")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["field"], "dose")

    def test_ingest_document_stores_copy_and_creates_note(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe")
        source = self.root / "outside-lab.txt"
        source.write_text("LDL 162 mg/dL\nHDL 44 mg/dL\n", encoding="utf-8")

        stored_path, note_path = ingest_document(
            self.root,
            "jane-doe",
            source,
            "lab",
            title="Outside lipid panel",
            source_date="2026-03-20",
        )

        profile = load_profile(self.root, "jane-doe")
        self.assertTrue(stored_path.exists())
        self.assertTrue(note_path.exists())
        self.assertEqual(profile["documents"][0]["title"], "Outside lipid panel")
        self.assertEqual(Path(profile["documents"][0]["archived_path"]).parent.name, "Archive")
        self.assertEqual(profile["encounters"][0]["kind"], "lab")

    def test_render_summary_includes_conflict_section(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe")
        upsert_record(
            self.root,
            "jane-doe",
            "conditions",
            {"name": "Asthma", "status": "stable"},
        )
        conflicts = load_conflicts(self.root, "jane-doe")
        profile = load_profile(self.root, "jane-doe")
        summary = render_summary_text(profile, conflicts, [], [], [])
        self.assertIn("Open Conflicts", summary)
        self.assertIn("Asthma", summary)

    def test_render_dossier_includes_notes_and_rules(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "conditions",
            {"name": "Asthma", "status": "stable"},
        )
        add_note(
            self.root,
            "",
            "Recent visit",
            "Pulmonology follow-up completed.",
        )
        record_vital(self.root, "", "2026-03-22", "heart_rate", "72", "bpm", "resting")
        profile = load_profile(self.root, "")
        conflicts = load_conflicts(self.root, "")
        dossier = render_dossier_text(profile, conflicts, ["Recent visit: Pulmonology follow-up completed."], [], [], [])

        self.assertIn("Health Dossier", dossier)
        self.assertIn("Asthma", dossier)
        self.assertIn("Working Rules For Claude", dossier)
        self.assertIn("Recent visit", dossier)

    def test_build_handoff_uses_visit_type_and_questions(self) -> None:
        ensure_person(self.root, "jane-doe", "Jane Doe", "1980-01-01", "female")
        upsert_record(
            self.root,
            "jane-doe",
            "conditions",
            {"name": "Hyperlipidemia"},
        )
        upsert_record(
            self.root,
            "jane-doe",
            "follow_up",
            {"task": "Discuss statin options"},
        )
        add_note(
            self.root,
            "jane-doe",
            "Recent labs",
            "LDL elevated on outside report.",
            source_type="document",
            source_label="outside lipid panel",
        )

        handoff = build_handoff(
            self.root,
            "jane-doe",
            "Cardiology consult for elevated LDL",
            "specialist",
            5,
        )

        self.assertIn("specialist", handoff)
        self.assertIn("Discuss statin options", handoff)
        self.assertIn("Recent labs", handoff)

    def test_refresh_views_writes_summary_and_dossier(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        refresh_views(self.root, "")
        self.assertTrue(summary_path(self.root, "").exists())
        self.assertTrue(dossier_path(self.root, "").exists())
        self.assertTrue(home_path(self.root, "").exists())
        self.assertTrue(patterns_path(self.root, "").exists())
        self.assertTrue(start_here_path(self.root, "").exists())
        self.assertTrue(today_path(self.root, "").exists())
        self.assertTrue(this_week_path(self.root, "").exists())
        self.assertTrue(next_appointment_path(self.root, "").exists())
        self.assertTrue(review_worklist_path(self.root, "").exists())
        self.assertTrue(care_status_path(self.root, "").exists())
        self.assertTrue(vitals_trends_path(self.root, "").exists())
        self.assertTrue(assistant_update_path(self.root, "").exists())

    def test_process_inbox_moves_files_to_archive(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        source = inbox_dir(self.root, "") / "lipid-panel.txt"
        source.write_text("LDL 162 mg/dL\n", encoding="utf-8")

        processed = process_inbox(self.root, "")

        self.assertEqual(len(processed), 1)
        archived_path, _ = processed[0]
        self.assertFalse(source.exists())
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.parent, archive_dir(self.root, ""))

    def test_process_inbox_extracts_labs_into_review_queue(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        source = inbox_dir(self.root, "") / "lipid-panel.txt"
        source.write_text("LDL 162 mg/dL 0-99 H\nHDL 44 mg/dL 40-999 N\n", encoding="utf-8")

        process_inbox(self.root, "")

        profile = load_profile(self.root, "")
        review_queue = load_review_queue(self.root, "")
        self.assertEqual(len(profile["recent_tests"]), 2)
        self.assertEqual(len(review_queue), 2)
        self.assertTrue(all(item["section"] == "recent_tests" for item in review_queue))
        self.assertEqual(profile["recent_tests"][0]["flag"], "high")
        self.assertEqual(review_queue[0]["tier"], "safe_to_auto_apply")

    def test_medication_history_tracks_updates(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "medications",
            {"name": "atorvastatin", "dose": "10 mg nightly", "status": "active"},
        )
        upsert_record(
            self.root,
            "",
            "medications",
            {"name": "atorvastatin", "dose": "20 mg nightly", "status": "active"},
        )

        history = load_medication_history(self.root, "")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["event_type"], "updated")

    def test_render_trends_uses_numeric_tests(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "recent_tests",
            {"name": "LDL", "value": "162", "unit": "mg/dL", "date": "2026-03-20"},
        )
        upsert_record(
            self.root,
            "",
            "recent_tests",
            {"name": "LDL", "value": "140", "unit": "mg/dL", "date": "2026-04-20"},
        )

        trends = render_trends_text(load_profile(self.root, ""))

        self.assertIn("LDL", trends)
        self.assertIn("change", trends)

    def test_refresh_views_writes_reconciliation_and_trends(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "medications",
            {"name": "atorvastatin", "dose": "10 mg nightly", "status": "active"},
        )
        refresh_views(self.root, "")

        self.assertTrue(trends_path(self.root, "").exists())
        self.assertTrue(reconciliation_path(self.root, "").exists())
        self.assertTrue(timeline_path(self.root, "").exists())
        self.assertTrue(change_report_path(self.root, "").exists())

    def test_render_calendar_ics_includes_due_date(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "follow_up",
            {"task": "Repeat lipid panel", "due_date": "2026-05-01", "status": "pending"},
        )

        ics = render_calendar_ics(load_profile(self.root, ""))

        self.assertIn("Repeat lipid panel", ics)
        self.assertIn("20260501", ics)

    def test_weight_tracking_records_and_loads_entries(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        record_weight(self.root, "", "2026-03-01", 82.5, "kg", "baseline")
        record_weight(self.root, "", "2026-03-15", 81.0, "kg", "after diet")

        entries = load_weight_entries(self.root, "")

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["value"], 81.0)

    def test_caregiver_dashboard_scans_multiple_projects(self) -> None:
        parent = self.root / "caregiver"
        parent.mkdir()
        first = parent / "jane"
        second = parent / "john"
        ensure_person(first, "", "Jane Doe")
        ensure_person(second, "", "John Doe")
        upsert_record(
            first,
            "",
            "follow_up",
            {"task": "Urgent PCP follow-up", "due_date": "2020-01-01", "status": "pending"},
        )
        refresh_views(first, "")
        refresh_views(second, "")

        dashboard = build_dashboard(parent)

        self.assertIn("Jane Doe", dashboard)
        self.assertIn("John Doe", dashboard)
        self.assertIn("Urgency", dashboard)
        self.assertIn("Reminders By Person", dashboard)

    def test_timeline_and_change_report_include_recent_events(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "follow_up",
            {"task": "Repeat lipid panel", "due_date": "2026-05-01", "status": "pending"},
        )
        add_note(self.root, "", "Recent visit", "Medication discussed.")
        record_weight(self.root, "", "2026-03-10", 82.0, "kg", "baseline")
        record_vital(self.root, "", "2026-03-11", "blood_pressure", "128/82", "mmHg", "home cuff")
        profile = load_profile(self.root, "")
        timeline = render_timeline_text(
            build_timeline_events(
                self.root,
                "",
                profile,
                load_medication_history(self.root, ""),
                load_weight_entries(self.root, ""),
                load_vital_entries(self.root, ""),
            )
        )
        report = render_change_report_text(
            profile,
            load_conflicts(self.root, ""),
            load_review_queue(self.root, ""),
            load_medication_history(self.root, ""),
            load_weight_entries(self.root, ""),
            load_vital_entries(self.root, ""),
            365,
        )
        self.assertIn("follow_up", timeline)
        self.assertIn("Weight Changes", report)
        self.assertIn("Other Vital Changes", report)
        self.assertIn("Cross-Record Connections", report)

    def test_user_facing_views_include_priorities_and_review_guidance(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        source = inbox_dir(self.root, "") / "lipid-panel.txt"
        source.write_text("LDL 162 mg/dL 0-99 H\n", encoding="utf-8")
        process_inbox(self.root, "")
        refresh_views(self.root, "")

        home_text = home_path(self.root, "").read_text(encoding="utf-8")
        patterns_text = patterns_path(self.root, "").read_text(encoding="utf-8")
        today_text = today_path(self.root, "").read_text(encoding="utf-8")
        review_text = review_worklist_path(self.root, "").read_text(encoding="utf-8")
        status_text = care_status_path(self.root, "").read_text(encoding="utf-8")

        self.assertIn("Health Home", home_text)
        self.assertIn("Connected Patterns", home_text)
        self.assertIn("Health Patterns", patterns_text)
        self.assertIn("Focus Now", today_text)
        self.assertIn("Probably Safe To Accept", review_text)
        self.assertIn("Care Status", status_text)

    def test_next_appointment_and_preferences_surface_in_views(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        profile = load_profile(self.root, "")
        profile["preferences"]["primary_caregiver"] = "Sam Doe"
        save_profile(self.root, "", profile)
        upsert_record(
            self.root,
            "",
            "follow_up",
            {"task": "Cardiology follow-up", "due_date": "2026-04-01", "status": "pending"},
        )
        upsert_record(
            self.root,
            "",
            "recent_tests",
            {"name": "LDL", "value": "162", "unit": "mg/dL", "date": "2026-03-20", "flag": "high"},
        )
        refresh_views(self.root, "")

        appointment_text = next_appointment_path(self.root, "").read_text(encoding="utf-8")
        dossier_text = dossier_path(self.root, "").read_text(encoding="utf-8")
        patterns_text = patterns_path(self.root, "").read_text(encoding="utf-8")

        self.assertIn("30-Second Summary", appointment_text)
        self.assertIn("Short Portal Message Draft", appointment_text)
        self.assertIn("Pattern Connections Worth Mentioning", appointment_text)
        self.assertIn("Best Questions To Ask", appointment_text)
        self.assertIn("Primary caregiver: Sam Doe", dossier_text)
        self.assertIn("Health Patterns", patterns_text)

    def test_vitals_and_exports_work(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "conditions",
            {"name": "Hypertension"},
        )
        upsert_record(
            self.root,
            "",
            "medications",
            {"name": "lisinopril", "dose": "10 mg daily", "status": "active"},
        )
        record_vital(self.root, "", "2026-03-12", "blood_pressure", "128/82", "mmHg", "home cuff")
        refresh_views(self.root, "")

        vitals_text = vitals_trends_path(self.root, "").read_text(encoding="utf-8")
        redacted = render_redacted_summary_text(load_profile(self.root, ""))
        packet = render_clinician_packet_text(load_profile(self.root, ""), "pcp", "Blood pressure follow-up")
        portal = render_portal_message_text(load_profile(self.root, ""), "blood pressure follow-up")

        self.assertIn("Blood Pressure", vitals_text)
        self.assertIn("Patient reference", redacted)
        self.assertNotIn("Jane Doe", redacted)
        self.assertIn("Clinician Packet", packet)
        self.assertIn("Portal Message Draft", portal)

    def test_process_inbox_creates_intake_and_assistant_updates(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        source = inbox_dir(self.root, "") / "lipid-panel.txt"
        source.write_text("LDL 162 mg/dL 0-99 H\n", encoding="utf-8")

        command_process_inbox(argparse.Namespace(root=str(self.root), person_id=""))

        intake_text = intake_summary_path(self.root, "").read_text(encoding="utf-8")
        assistant_text = assistant_update_path(self.root, "").read_text(encoding="utf-8")
        self.assertIn("Files processed", intake_text)
        self.assertIn("Assistant Update", assistant_text)

    def test_caregiver_handoff_includes_primary_caregiver(self) -> None:
        parent = self.root / "caregiver"
        parent.mkdir()
        first = parent / "jane"
        ensure_person(first, "", "Jane Doe")
        profile = load_profile(first, "")
        profile["preferences"]["primary_caregiver"] = "Sam Doe"
        save_profile(first, "", profile)
        refresh_views(first, "")

        handoff = build_caregiver_handoff(parent)

        self.assertIn("Caregiver Handoff", handoff)
        self.assertIn("Sam Doe", handoff)

    def test_patterns_surface_repeated_findings_and_timing(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(
            self.root,
            "",
            "recent_tests",
            {"name": "LDL", "value": "160", "unit": "mg/dL", "date": "2026-03-01", "flag": "high"},
        )
        upsert_record(
            self.root,
            "",
            "recent_tests",
            {"name": "LDL", "value": "180", "unit": "mg/dL", "date": "2026-03-20", "flag": "high"},
        )
        upsert_record(
            self.root,
            "",
            "medications",
            {"name": "atorvastatin", "dose": "20 mg nightly", "status": "active"},
        )
        record_vital(self.root, "", "2026-03-05", "blood_pressure", "132/84", "mmHg", "home cuff")
        record_vital(self.root, "", "2026-03-12", "blood_pressure", "136/86", "mmHg", "home cuff")
        refresh_views(self.root, "")

        patterns_text = patterns_path(self.root, "").read_text(encoding="utf-8")
        home_text = home_path(self.root, "").read_text(encoding="utf-8")

        self.assertIn("LDL has moved", patterns_text)
        self.assertIn("flagged abnormal on multiple recorded dates", patterns_text)
        self.assertIn("Blood pressure has been elevated", patterns_text)
        self.assertIn("Connected Patterns", home_text)


if __name__ == "__main__":
    unittest.main()
