"""Regression tests for bug-fix round 2: verified backlog + 4 newly found bugs."""

import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.care_workspace import (
    ensure_person,
    load_profile,
    record_weight,
    save_profile,
)


class _WS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1", "Test")

    def tearDown(self):
        shutil.rmtree(self.tmp)


# ── backlog ──────────────────────────────────────────────────────────────────

class MonthlyReportKeysTests(_WS):
    def test_weight_and_training_sections_render(self):
        from scripts.monthly_report import write_monthly_report
        p = load_profile(self.root, "p1")
        p["workouts"] = [
            {"type": "run", "date": (date.today() - timedelta(days=3)).isoformat(),
             "duration_min": 45, "distance_km": 8.0},
        ]
        save_profile(self.root, "p1", p)
        for offset, kg in [(10, 78.0), (2, 79.5)]:
            record_weight(self.root, "p1", (date.today() - timedelta(days=offset)).isoformat(),
                          kg, "kg", "test")
        path = write_monthly_report(self.root, "p1")
        text = Path(path).read_text()
        self.assertIn("45 minutes total", text)
        self.assertIn("79.5 kg", text)


class RecapDocumentsTests(_WS):
    def test_recent_document_listed(self):
        from scripts.recap import write_recap
        p = load_profile(self.root, "p1")
        p["documents"] = [{
            "title": "Lab report June", "doc_type": "lab_report",
            "source_date": date.today().isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }]
        save_profile(self.root, "p1", p)
        path = write_recap(self.root, "p1")
        text = Path(path).read_text()
        self.assertIn("Lab report June", text)
        self.assertNotIn("No new documents this week", text)


class LoincFshTests(unittest.TestCase):
    def test_fsh_and_estradiol_both_mapped(self):
        from scripts.fhir_import import LOINC_TO_METRIC
        self.assertEqual(LOINC_TO_METRIC["15067-2"][0], "FSH")
        self.assertEqual(LOINC_TO_METRIC["2243-4"][0], "Estradiol")
        self.assertEqual(LOINC_TO_METRIC["2093-3"][0], "Total Cholesterol")


class WeightGainNudgeTests(_WS):
    def test_rapid_gain_alerts(self):
        from scripts.nudges import compute_nudges
        for offset, kg in [(10, 78.0), (5, 79.5), (1, 80.6)]:
            record_weight(self.root, "p1", (date.today() - timedelta(days=offset)).isoformat(),
                          kg, "kg", "test")
        titles = [n["title"].lower() for n in compute_nudges(self.root, "p1")]
        self.assertTrue(any("weight up" in t for t in titles),
                        f"weight-gain nudge missing: {titles}")


class PrediabetesTests(unittest.TestCase):
    def test_prediabetes_does_not_loosen_hba1c(self):
        from scripts.lab_ranges import flag_lab_value
        profile = {"conditions": [{"name": "prediabetes"}], "medications": []}
        # 6.4% is abnormal for a prediabetic; treated-diabetes target (<7.0) must not apply
        self.assertNotEqual(flag_lab_value("HbA1c", 6.4, profile), "normal")

    def test_real_diabetes_still_gets_treatment_target(self):
        from scripts.lab_ranges import flag_lab_value
        profile = {"conditions": [{"name": "type 2 diabetes"}], "medications": []}
        self.assertEqual(flag_lab_value("HbA1c", 6.4, profile), "normal")


class EmptyMedNameTests(unittest.TestCase):
    def test_nameless_med_matches_nothing(self):
        from scripts.lab_ranges import personalised_range
        profile = {"conditions": [], "medications": [{"name": ""}]}
        r = personalised_range("TSH", profile)
        # levothyroxine adjustment (0.5-2.5) must NOT fire for a nameless med
        self.assertNotEqual(r.get("high"), 2.5)


class TriageTests(unittest.TestCase):
    def test_severe_worsening_escalates_to_emergency(self):
        from scripts.triage import assess
        band = assess({"q1": "headache", "q3": "9/10", "q4": "getting worse"})["band"]
        self.assertEqual(band, "Emergency now")

    def test_bare_number_severity_parsed(self):
        from scripts.triage import assess
        result = assess({"q1": "back pain", "q3": "8, constant"})
        self.assertEqual(result["severity"], 8)


class CsvCommaTests(_WS):
    def test_thousands_comma_steps_imported(self):
        from scripts.wearable_import import import_wearable_file
        p = self.root / "steps.csv"
        p.write_text('date,metric,value,unit\n2025-06-01,steps,"8,421",\n')
        counts = import_wearable_file(self.root, "p1", p)
        self.assertEqual(counts.get("steps"), 1)


# ── 4 new bugs ───────────────────────────────────────────────────────────────

class MealsPersistTests(_WS):
    def test_logged_meal_survives_save(self):
        p = load_profile(self.root, "p1")
        p.setdefault("meals", []).append({"date": date.today().isoformat(), "text": "chicken 200g"})
        save_profile(self.root, "p1", p)
        reloaded = load_profile(self.root, "p1")
        self.assertEqual(len(reloaded.get("meals", [])), 1)


class VisitHistoryPersistTests(_WS):
    def test_visit_record_survives_save(self):
        p = load_profile(self.root, "p1")
        p.setdefault("visit_history", []).append(
            {"date": date.today().isoformat(), "notes": "dose increased"})
        save_profile(self.root, "p1", p)
        reloaded = load_profile(self.root, "p1")
        self.assertEqual(len(reloaded.get("visit_history", [])), 1)


class MensHealthLabsTests(unittest.TestCase):
    def test_psa_read_from_recent_tests(self):
        from scripts.mens_health import build_mens_health_report
        profile = {
            "name": "Test", "sex": "male", "date_of_birth": "1970-01-01",
            "conditions": [], "medications": [], "daily_checkins": [],
            "screenings": [], "family_history": [], "workouts": [],
            "recent_tests": [
                {"name": "PSA", "value": 6.2, "unit": "ng/mL",
                 "date": date.today().isoformat()},
            ],
        }
        report = build_mens_health_report(profile)
        self.assertNotIn("No PSA results found", report)
        self.assertIn("6.2", report)


class DecisionsEmptyAgeTests(unittest.TestCase):
    def test_blank_age_at_diagnosis_no_crash(self):
        from scripts.decisions import screening_intensity_decision
        profile = {
            "name": "Test", "sex": "female", "date_of_birth": "1980-01-01",
            "conditions": [], "medications": [],
            "family_history": [
                {"relation": "mother", "condition": "breast cancer", "age_at_diagnosis": ""},
            ],
        }
        result = screening_intensity_decision(profile)  # must not raise
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
