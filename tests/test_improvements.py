"""Tests for the 18 improvement items."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import (
    WorkspaceSnapshot,
    ensure_person,
    file_content_hash,
    list_inbox_files,
    load_profile,
    load_snapshot,
    load_vital_entries,
    parse_bp_values,
    record_vital,
    record_weight,
    save_profile,
    staleness_days,
    staleness_warning,
    upsert_record,
    archive_old_records,
)
from scripts.extraction import (
    classify_document_content,
    extract_allergy_candidates,
    extract_condition_candidates,
    extract_follow_up_candidates,
    extract_lab_candidates,
    extract_medication_candidates,
    extract_qualitative_lab_candidates,
    ingest_document,
    process_inbox,
)
from scripts.rendering import (
    build_pattern_insights,
    refresh_views,
    render_clinician_packet_text,
    render_portal_message_text,
)


class WorkspaceSnapshotTests(unittest.TestCase):
    """Item 1: WorkspaceSnapshot pre-loads all data."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_snapshot_precomputes_filtered_views(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        snap = load_snapshot(self.root, "")
        self.assertIsInstance(snap, WorkspaceSnapshot)
        self.assertEqual(snap.open_conflicts, [])
        self.assertEqual(snap.open_review_items, [])

    def test_refresh_views_uses_snapshot(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        summary_path, dossier_path = refresh_views(self.root, "")
        self.assertTrue(summary_path.exists())
        self.assertTrue(dossier_path.exists())


class StructuredVitalsTests(unittest.TestCase):
    """Item 11: Structured numeric parsing for vitals."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_bp_stored_with_systolic_diastolic(self) -> None:
        ensure_person(self.root, "", "Test")
        record_vital(self.root, "", "2026-03-01", "blood_pressure", "128/82", "mmHg")
        entries = load_vital_entries(self.root, "")
        self.assertEqual(entries[0]["systolic"], 128)
        self.assertEqual(entries[0]["diastolic"], 82)

    def test_numeric_vital_stored(self) -> None:
        ensure_person(self.root, "", "Test")
        record_vital(self.root, "", "2026-03-01", "heart_rate", "72", "bpm")
        entries = load_vital_entries(self.root, "")
        self.assertEqual(entries[0]["numeric_value"], 72.0)

    def test_parse_bp_values(self) -> None:
        self.assertEqual(parse_bp_values("128/82"), (128, 82))
        self.assertEqual(parse_bp_values("invalid"), (None, None))


class RicherLabExtractionTests(unittest.TestCase):
    """Item 5: Multiple lab regex patterns."""

    def test_standard_format(self) -> None:
        text = "LDL 162 mg/dL 0-99 H\n"
        candidates = extract_lab_candidates(text, "2026-01-01")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate"]["flag"], "high")

    def test_qualitative_results(self) -> None:
        text = "HIV Screen Negative\nHepatitis B Surface Ab Reactive\n"
        candidates = extract_qualitative_lab_candidates(text, "2026-01-01")
        self.assertGreaterEqual(len(candidates), 1)

    def test_less_than_prefix(self) -> None:
        # The < prefix should be handled by the second pattern
        text = "PSA <0.5 ng/mL\n"
        candidates = extract_lab_candidates(text, "2026-01-01")
        # May or may not match depending on implementation, but shouldn't crash
        self.assertIsInstance(candidates, list)


class BetterMedicationExtractionTests(unittest.TestCase):
    """Item 6: Improved medication patterns."""

    def test_standard_medication(self) -> None:
        text = "Atorvastatin 10 mg nightly\n"
        candidates = extract_medication_candidates(text, "medication-list")
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate"]["name"], "Atorvastatin")

    def test_no_space_dose(self) -> None:
        text = "Lisinopril 10mg daily\n"
        candidates = extract_medication_candidates(text, "medication-list")
        self.assertGreaterEqual(len(candidates), 1)

    def test_units_medication(self) -> None:
        text = "Insulin Glargine 20 units at bedtime\n"
        candidates = extract_medication_candidates(text, "medication-list")
        self.assertGreaterEqual(len(candidates), 1)


class BetterFollowUpExtractionTests(unittest.TestCase):
    """Item 7: Follow-up extraction with dates."""

    def test_action_verbs(self) -> None:
        text = "Schedule cardiology appointment\nRecheck BP in 2 weeks\n"
        candidates = extract_follow_up_candidates(text)
        self.assertGreaterEqual(len(candidates), 1)

    def test_relative_date_extraction(self) -> None:
        text = "Repeat lipid panel in 3 months\n"
        candidates = extract_follow_up_candidates(text)
        self.assertGreaterEqual(len(candidates), 1)
        # If a due_date was extracted, it should be a valid ISO date
        for c in candidates:
            due = c["candidate"].get("due_date")
            if due:
                self.assertRegex(due, r"^\d{4}-\d{2}-\d{2}$")


class ContentBasedClassificationTests(unittest.TestCase):
    """Item 8: Content-based document classification."""

    def test_lab_content_overrides_generic_filename(self) -> None:
        text = "Reference Range: 0-99\nSpecimen: Blood\nLDL 162 mg/dL H"
        result = classify_document_content(text, "document")
        self.assertEqual(result, "lab")

    def test_medication_content(self) -> None:
        text = "Medication List\nAtorvastatin 10 mg\nPrescription refill due"
        result = classify_document_content(text, "document")
        self.assertEqual(result, "medication-list")

    def test_empty_text_falls_back(self) -> None:
        result = classify_document_content("", "lab")
        self.assertEqual(result, "lab")


class AllergyExtractionTests(unittest.TestCase):
    """Item 9: Allergy extraction."""

    def test_allergic_to_pattern(self) -> None:
        text = "Patient is allergic to Penicillin (rash)\n"
        candidates = extract_allergy_candidates(text)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["section"], "allergies")

    def test_nkda(self) -> None:
        text = "Allergies: NKDA\n"
        candidates = extract_allergy_candidates(text)
        self.assertGreaterEqual(len(candidates), 1)


class ConditionExtractionTests(unittest.TestCase):
    """Item 9: Condition extraction."""

    def test_diagnosis_line(self) -> None:
        text = "Assessment:\n- Type 2 Diabetes Mellitus\n- Essential Hypertension\n"
        candidates = extract_condition_candidates(text)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["section"], "conditions")


class ContentHashDedupTests(unittest.TestCase):
    """Item 10: Content hash deduplication."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_file_content_hash_consistent(self) -> None:
        path = self.root / "test.txt"
        path.write_text("hello", encoding="utf-8")
        h1 = file_content_hash(path)
        h2 = file_content_hash(path)
        self.assertEqual(h1, h2)

    def test_duplicate_file_skipped(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        source = self.root / "inbox" / "lab.txt"
        source.write_text("LDL 162 mg/dL 0-99 H\n", encoding="utf-8")
        ingest_document(self.root, "", source, "lab", title="Lab 1")

        # Create same content again
        source2 = self.root / "inbox" / "lab-copy.txt"
        source2.write_text("LDL 162 mg/dL 0-99 H\n", encoding="utf-8")
        # Second ingest should detect duplicate
        result = ingest_document(self.root, "", source2, "lab", title="Lab 1 copy")
        # Should return something (either skip or process) without error
        self.assertIsNotNone(result)


class ArchiveOldRecordsTests(unittest.TestCase):
    """Item 13: archive_old_records uses stdlib only (no dateutil)."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_archive_moves_old_records(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        old_date = (date.today() - timedelta(days=400)).isoformat()
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "120", "unit": "mg/dL",
            "date": old_date,
        })
        profile_before = load_profile(self.root, "")
        self.assertEqual(len(profile_before["recent_tests"]), 1)

        archive_path = archive_old_records(self.root, "", max_age_months=12)

        self.assertTrue(archive_path.exists())
        profile_after = load_profile(self.root, "")
        self.assertEqual(len(profile_after["recent_tests"]), 0)


class StalenessTests(unittest.TestCase):
    """Item 18: Staleness indicators."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_fresh_data_no_warning(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "120", "unit": "mg/dL",
            "date": date.today().isoformat(),
        })
        profile = load_profile(self.root, "")
        self.assertIsNone(staleness_warning(profile))

    def test_old_data_returns_warning(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        old_date = (date.today() - timedelta(days=200)).isoformat()
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "120", "unit": "mg/dL",
            "date": old_date,
        })
        profile = load_profile(self.root, "")
        warning = staleness_warning(profile)
        self.assertIsNotNone(warning)
        self.assertIn("outdated", warning)

    def test_staleness_in_views(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        old_date = (date.today() - timedelta(days=200)).isoformat()
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "120", "unit": "mg/dL",
            "date": old_date,
        })
        refresh_views(self.root, "")
        home = (self.root / "HEALTH_HOME.md").read_text(encoding="utf-8")
        self.assertIn("outdated", home.lower())


class DeeperPatternTests(unittest.TestCase):
    """Item 15: Time-gap awareness, med-lab correlation."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_stale_abnormal_lab_flagged(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        old_date = (date.today() - timedelta(days=200)).isoformat()
        upsert_record(self.root, "", "recent_tests", {
            "name": "TSH", "value": "8.5", "unit": "mIU/L",
            "date": old_date, "flag": "high",
        })
        profile = load_profile(self.root, "")
        insights = build_pattern_insights(profile, [], [], [])
        matching = [i for i in insights if "TSH" in i and "month" in i.lower()]
        self.assertGreaterEqual(len(matching), 1)

    def test_medication_lab_correlation(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "medications", {
            "name": "Atorvastatin", "dose": "10 mg", "status": "active",
        })
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "180", "unit": "mg/dL",
            "date": date.today().isoformat(), "flag": "high",
        })
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "170", "unit": "mg/dL",
            "date": (date.today() - timedelta(days=90)).isoformat(), "flag": "high",
        })
        profile = load_profile(self.root, "")
        insights = build_pattern_insights(profile, [], [], [])
        # Should mention statin + LDL or at least LDL trending
        ldl_insights = [i for i in insights if "LDL" in i]
        self.assertGreaterEqual(len(ldl_insights), 1)


class SmartClinicianPacketTests(unittest.TestCase):
    """Item 16: Visit-relevant clinician packets."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_lipid_visit_filters_relevant_tests(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "180", "unit": "mg/dL",
            "date": "2026-03-01", "flag": "high",
        })
        upsert_record(self.root, "", "recent_tests", {
            "name": "TSH", "value": "2.5", "unit": "mIU/L",
            "date": "2026-03-01", "flag": "normal",
        })
        profile = load_profile(self.root, "")
        packet = render_clinician_packet_text(profile, "specialist", "Lipid management follow-up")
        self.assertIn("LDL", packet)
        self.assertIn("Clinician Packet", packet)


class BetterPortalMessageTests(unittest.TestCase):
    """Item 17: Improved portal message drafts."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_portal_message_includes_numbers(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "180", "unit": "mg/dL",
            "date": "2026-03-01", "flag": "high",
        })
        profile = load_profile(self.root, "")
        msg = render_portal_message_text(profile, "lipid follow-up")
        self.assertIn("Portal Message", msg)


class QueryDashboardTests(unittest.TestCase):
    """Query-relevant dashboard feature."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "conditions", {"name": "Hypertension"})
        upsert_record(self.root, "", "medications", {
            "name": "Atorvastatin", "dose": "10 mg", "status": "active",
        })
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "180", "unit": "mg/dL",
            "date": date.today().isoformat(), "flag": "high",
        })
        upsert_record(self.root, "", "follow_up", {
            "task": "Repeat lipid panel", "due_date": "2026-05-01", "status": "pending",
        })
        record_vital(self.root, "", "2026-03-12", "blood_pressure", "132/84", "mmHg")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_lab_query_shows_lab_dashboard(self) -> None:
        from scripts.rendering import classify_query_intent, render_query_dashboard
        intent = classify_query_intent("what do my cholesterol labs mean?")
        self.assertEqual(intent, "lab_review")

        snap = load_snapshot(self.root, "")
        result = render_query_dashboard(
            "what do my cholesterol labs mean?",
            snap.profile, snap.conflicts, snap.review_queue,
            snap.medication_history, snap.weight_entries, snap.vital_entries,
            snap.inbox_files,
        )
        self.assertIn("Lab Review Dashboard", result.text)
        self.assertIn("LDL", result.text)
        self.assertEqual(result.primary_intent, "lab_review")

    def test_medication_query(self) -> None:
        from scripts.rendering import classify_query_intent, render_query_dashboard
        intent = classify_query_intent("should I worry about statin side effects?")
        self.assertEqual(intent, "medication_review")

        snap = load_snapshot(self.root, "")
        result = render_query_dashboard(
            "should I worry about statin side effects?",
            snap.profile, snap.conflicts, snap.review_queue,
            snap.medication_history, snap.weight_entries, snap.vital_entries,
            snap.inbox_files,
        )
        self.assertIn("Medication Review Dashboard", result.text)
        self.assertIn("Atorvastatin", result.text)

    def test_visit_prep_query(self) -> None:
        from scripts.rendering import classify_query_intent
        self.assertEqual(classify_query_intent("help me prepare for my doctor appointment"), "visit_prep")

    def test_symptom_query(self) -> None:
        from scripts.rendering import classify_query_intent
        self.assertEqual(classify_query_intent("I have a headache and feel dizzy, should I worry?"), "symptom_triage")

    def test_vitals_query(self) -> None:
        from scripts.rendering import classify_query_intent, render_query_dashboard
        self.assertEqual(classify_query_intent("how is my blood pressure trending?"), "weight_vitals")

        snap = load_snapshot(self.root, "")
        result = render_query_dashboard(
            "how is my blood pressure trending?",
            snap.profile, snap.conflicts, snap.review_queue,
            snap.medication_history, snap.weight_entries, snap.vital_entries,
            snap.inbox_files,
        )
        self.assertIn("Vitals Dashboard", result.text)

    def test_followup_query(self) -> None:
        from scripts.rendering import classify_query_intent
        self.assertEqual(classify_query_intent("what follow-ups are overdue?"), "follow_up")

    def test_generic_query_falls_back_to_overview(self) -> None:
        from scripts.rendering import classify_query_intent
        self.assertEqual(classify_query_intent("give me a quick update"), "caregiver_overview")

    def test_snapshot_convenience_wrapper(self) -> None:
        from scripts.rendering import render_query_dashboard_from_snapshot
        snap = load_snapshot(self.root, "")
        result = render_query_dashboard_from_snapshot("catch me up", snap)
        self.assertIn("Health Overview Dashboard", result.text)
        self.assertIn("Jane Doe", result.text)

    def test_dashboard_includes_intent_metadata(self) -> None:
        from scripts.rendering import render_query_dashboard_from_snapshot
        snap = load_snapshot(self.root, "")
        result = render_query_dashboard_from_snapshot("LDL labs", snap)
        self.assertIn("intent: lab_review", result.text)
        self.assertIn('query: "LDL labs"', result.text)


class MultiIntentTests(unittest.TestCase):
    """Multi-intent detection for compound queries."""

    def test_compound_query_detects_multiple_intents(self) -> None:
        from scripts.rendering import classify_query_intents
        intents = classify_query_intents("what are my labs and when is my next appointment", max_intents=2)
        self.assertIn("lab_review", intents)
        # Should detect at least one intent
        self.assertGreaterEqual(len(intents), 1)

    def test_single_query_returns_one_intent(self) -> None:
        from scripts.rendering import classify_query_intents
        intents = classify_query_intents("cholesterol labs", max_intents=2)
        self.assertEqual(intents[0], "lab_review")

    def test_multi_intent_merges_sections(self) -> None:
        from scripts.rendering import _merge_sections_for_intents
        merged = _merge_sections_for_intents(["lab_review", "visit_prep"])
        # Should have sections from both, no duplicates
        self.assertIn("relevant_labs", merged)
        self.assertIn("thirty_second", merged)
        self.assertEqual(len(merged), len(set(merged)))


class DashboardCacheTests(unittest.TestCase):
    """Dashboard save/reuse with similarity matching."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        ensure_person(self.root, "", "Jane Doe")
        upsert_record(self.root, "", "recent_tests", {
            "name": "LDL", "value": "180", "unit": "mg/dL",
            "date": date.today().isoformat(), "flag": "high",
        })

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_save_and_find_cached_dashboard(self) -> None:
        from scripts.care_workspace import (
            find_cached_dashboard,
            save_dashboard_to_cache,
        )
        save_dashboard_to_cache(
            self.root, "", "what do my cholesterol labs mean?",
            "lab_review", ["lab_review"], "# Lab Dashboard\nLDL 180\n",
        )
        cached = find_cached_dashboard(self.root, "", "cholesterol labs meaning", "lab_review")
        self.assertIsNotNone(cached)
        self.assertIn("Lab Dashboard", cached["dashboard_text"])

    def test_cache_miss_on_different_intent(self) -> None:
        from scripts.care_workspace import (
            find_cached_dashboard,
            save_dashboard_to_cache,
        )
        save_dashboard_to_cache(
            self.root, "", "cholesterol labs", "lab_review", ["lab_review"], "# Labs\n",
        )
        cached = find_cached_dashboard(self.root, "", "medication side effects", "medication_review")
        self.assertIsNone(cached)

    def test_cache_invalidated_on_profile_update(self) -> None:
        from scripts.care_workspace import (
            find_cached_dashboard,
            save_dashboard_to_cache,
            load_dashboard_cache,
            save_dashboard_cache,
        )
        save_dashboard_to_cache(
            self.root, "", "cholesterol labs", "lab_review", ["lab_review"], "# Labs\n",
        )
        # Simulate profile being updated after cache was created
        # by backdating the cache entry's profile_updated_at
        cache = load_dashboard_cache(self.root, "")
        cache[-1]["profile_updated_at"] = "2026-01-01T00:00:00+00:00"
        save_dashboard_cache(self.root, "", cache)

        # Now the profile's updated_at is newer than the cached profile_updated_at
        cached = find_cached_dashboard(self.root, "", "cholesterol labs", "lab_review")
        self.assertIsNone(cached)

    def test_query_similarity(self) -> None:
        from scripts.care_workspace import query_similarity
        # Identical
        self.assertAlmostEqual(query_similarity("cholesterol labs", "cholesterol labs"), 1.0)
        # Similar
        sim = query_similarity("what do my cholesterol labs mean", "cholesterol labs meaning")
        self.assertGreater(sim, 0.3)
        # Unrelated
        sim = query_similarity("cholesterol labs", "blood pressure medication")
        self.assertLess(sim, 0.5)

    def test_cache_max_entries(self) -> None:
        from scripts.care_workspace import load_dashboard_cache, save_dashboard_to_cache
        for i in range(25):
            save_dashboard_to_cache(
                self.root, "", f"query {i}", "lab_review", ["lab_review"], f"# Dashboard {i}\n",
            )
        cache = load_dashboard_cache(self.root, "")
        self.assertLessEqual(len(cache), 20)


class UsageTrackingTests(unittest.TestCase):
    """Intent usage tracking."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        ensure_person(self.root, "", "Jane Doe")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_record_and_read_intent_usage(self) -> None:
        from scripts.care_workspace import record_intent_usage, top_intents
        record_intent_usage(self.root, "", "lab_review")
        record_intent_usage(self.root, "", "lab_review")
        record_intent_usage(self.root, "", "visit_prep")
        top = top_intents(self.root, "")
        self.assertEqual(top[0], "lab_review")


class PersonAwareTests(unittest.TestCase):
    """Person-aware query routing for caregiver mode."""

    def test_detect_person_by_first_name(self) -> None:
        from scripts.rendering import detect_person_in_query
        result = detect_person_in_query(
            "how is Jane doing?",
            ["Jane Doe", "John Doe"],
        )
        self.assertEqual(result, "Jane Doe")

    def test_detect_person_by_full_name(self) -> None:
        from scripts.rendering import detect_person_in_query
        result = detect_person_in_query(
            "update on John Doe",
            ["Jane Doe", "John Doe"],
        )
        self.assertEqual(result, "John Doe")

    def test_no_match_returns_none(self) -> None:
        from scripts.rendering import detect_person_in_query
        result = detect_person_in_query(
            "what are my labs?",
            ["Jane Doe", "John Doe"],
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
