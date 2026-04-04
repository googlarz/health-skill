"""Edge-case and robustness tests for Health Skill."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import (
    ensure_person,
    load_profile,
    profile_path,
    save_profile,
    upsert_record,
    add_note,
    atomic_write_text,
)
from scripts.extraction import (
    extract_lab_candidates,
    list_inbox_files,
    process_inbox,
)
from scripts.rendering import refresh_views


class CorruptJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_load_profile_raises_on_corrupt_json(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        path = profile_path(self.root, "")
        path.write_text("{invalid json!!!", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            load_profile(self.root, "")

    def test_load_profile_raises_when_missing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_profile(self.root, "nonexistent")

    def test_save_profile_survives_empty_sections(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        profile = load_profile(self.root, "")
        profile["conditions"] = []
        profile["medications"] = []
        profile["allergies"] = []
        save_profile(self.root, "", profile)
        reloaded = load_profile(self.root, "")
        self.assertEqual(reloaded["conditions"], [])


class UnicodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_unicode_person_name(self) -> None:
        ensure_person(self.root, "", "Müller Straße")
        profile = load_profile(self.root, "")
        self.assertEqual(profile["name"], "Müller Straße")

    def test_unicode_condition_name(self) -> None:
        ensure_person(self.root, "", "Test User")
        upsert_record(
            self.root, "", "conditions",
            {"name": "Ménière's disease", "status": "stable"},
        )
        profile = load_profile(self.root, "")
        self.assertEqual(profile["conditions"][0]["name"], "Ménière's disease")

    def test_unicode_note_body(self) -> None:
        ensure_person(self.root, "", "Test User")
        note_path = add_note(
            self.root, "", "日本語テスト",
            "血圧は正常です。",
        )
        self.assertTrue(note_path.exists())
        content = note_path.read_text(encoding="utf-8")
        self.assertIn("血圧は正常です", content)


class EmptyInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_process_empty_inbox(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        processed = process_inbox(self.root, "")
        self.assertEqual(processed, [])

    def test_list_inbox_files_on_empty_inbox(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        files = list_inbox_files(self.root, "")
        self.assertEqual(files, [])

    def test_dry_run_does_not_move_files(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        inbox = self.root / "inbox"
        source = inbox / "lab.txt"
        source.write_text("LDL 162 mg/dL\n", encoding="utf-8")
        result = process_inbox(self.root, "", dry_run=True)
        self.assertEqual(result, [])
        self.assertTrue(source.exists(), "dry-run should not move files")


class ExtractionEdgeCases(unittest.TestCase):
    def test_extract_lab_candidates_empty_text(self) -> None:
        candidates = extract_lab_candidates("", "2026-01-01")
        self.assertEqual(candidates, [])

    def test_extract_lab_candidates_garbage_text(self) -> None:
        candidates = extract_lab_candidates(
            "This is not a lab report at all.\nJust random text with numbers 42.",
            "2026-01-01",
        )
        self.assertEqual(candidates, [])

    def test_extract_lab_with_no_flag(self) -> None:
        candidates = extract_lab_candidates(
            "TSH 2.5 mIU/L 0.4-4.0\n",
            "2026-01-01",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate"]["flag"], "in_range")


class RefreshViewsEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_refresh_views_on_fresh_empty_project(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        summary_path, dossier_path = refresh_views(self.root, "")
        self.assertTrue(summary_path.exists())
        self.assertTrue(dossier_path.exists())

    def test_refresh_views_with_many_records(self) -> None:
        ensure_person(self.root, "", "Jane Doe")
        for i in range(20):
            upsert_record(
                self.root, "", "recent_tests",
                {"name": f"Test-{i}", "value": str(i * 10), "unit": "mg/dL", "date": f"2026-01-{i+1:02d}"},
            )
        summary_path, dossier_path = refresh_views(self.root, "")
        self.assertTrue(summary_path.exists())


if __name__ == "__main__":
    unittest.main()
