"""Tests for v2.2 features: interactions, lab ranges, side effects, monthly report,
FHIR import, mental health, pattern alerts, CLI wiring."""

import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.commands import build_parser
from scripts.fhir_import import import_fhir_file, is_fhir_file
from scripts.interactions import check_interactions, render_interactions_text
from scripts.lab_ranges import flag_lab_value, personalised_range
from scripts.mental_health import (
    build_mental_health_report,
    detect_burnout,
    score_gad2_from_checkins,
    score_phq2_from_checkins,
)
from scripts.monthly_report import build_monthly_report
from scripts.side_effects import analyse_side_effects


# ---------------------------------------------------------------------------
# Interaction tests
# ---------------------------------------------------------------------------

class InteractionTests(unittest.TestCase):
    def _profile(self, meds, conditions=None):
        return {
            "medications": [{"name": m} for m in meds],
            "conditions": [{"name": c} for c in (conditions or [])],
        }

    def test_warfarin_nsaid_critical(self):
        alerts = check_interactions(self._profile(["warfarin", "ibuprofen"]))
        self.assertTrue(any(a["severity"] == "critical" for a in alerts))

    def test_ssri_maoi_critical(self):
        alerts = check_interactions(self._profile(["sertraline", "phenelzine"]))
        self.assertTrue(any(a["severity"] == "critical" for a in alerts))

    def test_statin_clarithromycin_major(self):
        alerts = check_interactions(self._profile(["atorvastatin", "clarithromycin"]))
        self.assertTrue(any(a["severity"] == "major" for a in alerts))

    def test_no_meds_no_alerts(self):
        self.assertEqual(check_interactions(self._profile([])), [])

    def test_safe_combo_no_alert(self):
        alerts = check_interactions(self._profile(["paracetamol", "amoxicillin"]))
        self.assertEqual(alerts, [])

    def test_drug_condition_metformin_ckd(self):
        alerts = check_interactions(self._profile(
            ["metformin"], ["chronic kidney disease"]
        ))
        self.assertTrue(any(a["type"] == "drug-condition" for a in alerts))

    def test_sorted_critical_first(self):
        alerts = check_interactions(self._profile(["warfarin", "ibuprofen", "sertraline", "phenelzine"]))
        if len(alerts) >= 2:
            self.assertEqual(alerts[0]["severity"], "critical")

    def test_render_no_alerts(self):
        text = render_interactions_text(self._profile(["paracetamol"]))
        self.assertIn("No significant", text)

    def test_render_with_alerts(self):
        text = render_interactions_text(self._profile(["warfarin", "ibuprofen"]))
        self.assertIn("CRITICAL", text)
        self.assertIn("bleeding", text.lower())


# ---------------------------------------------------------------------------
# Lab range tests
# ---------------------------------------------------------------------------

class LabRangeTests(unittest.TestCase):
    def _profile(self, conditions=None, medications=None, sex=""):
        return {
            "sex": sex,
            "conditions": [{"name": c} for c in (conditions or [])],
            "medications": [{"name": m} for m in (medications or [])],
        }

    def test_base_ldl_range(self):
        r = personalised_range("LDL", self._profile())
        self.assertEqual(r["high"], 130)

    def test_diabetes_tightens_ldl(self):
        r = personalised_range("LDL", self._profile(conditions=["type 2 diabetes"]))
        self.assertLessEqual(r["high"], 100)

    def test_levothyroxine_tightens_tsh(self):
        r = personalised_range("TSH", self._profile(medications=["levothyroxine"]))
        self.assertLessEqual(r["high"], 2.5)
        self.assertTrue(len(r["notes"]) > 0)

    def test_sex_adjusts_hemoglobin(self):
        r_f = personalised_range("Hemoglobin", self._profile(sex="female"))
        r_m = personalised_range("Hemoglobin", self._profile(sex="male"))
        self.assertLess(r_f["high"], r_m["high"])

    def test_flag_high(self):
        self.assertEqual(flag_lab_value("LDL", 165, self._profile()), "high")

    def test_flag_normal(self):
        self.assertEqual(flag_lab_value("LDL", 95, self._profile()), "normal")

    def test_flag_low(self):
        self.assertEqual(flag_lab_value("Glucose", 60, self._profile()), "low")

    def test_unknown_marker_returns_empty(self):
        r = personalised_range("BogusXYZ", self._profile())
        self.assertIsNone(r["low"])

    def test_metformin_raises_b12_floor(self):
        r = personalised_range("Vitamin B12", self._profile(medications=["metformin"]))
        self.assertGreaterEqual(r["low"], 300)


# ---------------------------------------------------------------------------
# Side-effect tests
# ---------------------------------------------------------------------------

class SideEffectTests(unittest.TestCase):
    def _make_profile(self, med_name: str, start_offset_days: int, pain_before: float, pain_after: float):
        start = (date.today() - timedelta(days=start_offset_days)).isoformat()
        checkins = []
        for i in range(30, start_offset_days + 10):
            d = (date.today() - timedelta(days=i)).isoformat()
            checkins.append({"date": d, "mood": 7, "energy": 7, "pain": pain_before, "sleep_hours": 7})
        for i in range(start_offset_days - 1, 0, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            checkins.append({"date": d, "mood": 6, "energy": 6, "pain": pain_after, "sleep_hours": 7})
        return {
            "medications": [{"name": med_name, "start_date": start}],
            "daily_checkins": checkins,
        }

    def test_statin_myalgia_detected(self):
        profile = self._make_profile("atorvastatin", 21, pain_before=1.0, pain_after=4.5)
        findings = analyse_side_effects(profile)
        self.assertTrue(any("statin" in f["effect_name"].lower() for f in findings))

    def test_no_signal_below_threshold(self):
        profile = self._make_profile("atorvastatin", 21, pain_before=1.0, pain_after=2.0)
        findings = analyse_side_effects(profile)
        # delta < 2.0 — should not trigger
        statin = [f for f in findings if "statin" in f["effect_name"].lower()]
        self.assertEqual(len(statin), 0)

    def test_no_start_date_no_finding(self):
        profile = {
            "medications": [{"name": "atorvastatin"}],  # no start_date
            "daily_checkins": [],
        }
        self.assertEqual(analyse_side_effects(profile), [])

    def test_empty_profile_no_crash(self):
        self.assertEqual(analyse_side_effects({}), [])


# ---------------------------------------------------------------------------
# Monthly report tests
# ---------------------------------------------------------------------------

class MonthlyReportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1985-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_renders_without_error(self):
        profile = load_profile(self.root, "me")
        text = build_monthly_report(profile, self.root, "me")
        self.assertIn("Monthly Report", text)

    def test_includes_action_item(self):
        profile = load_profile(self.root, "me")
        text = build_monthly_report(profile, self.root, "me")
        self.assertIn("One thing to do", text)

    def test_checkin_trends_shown(self):
        profile = load_profile(self.root, "me")
        for i in range(15):
            d = (date.today() - timedelta(days=i)).isoformat()
            profile.setdefault("daily_checkins", []).append({
                "date": d, "mood": 7, "energy": 6, "pain": 2, "sleep_hours": 7.5
            })
        save_profile(self.root, "me", profile)
        profile = load_profile(self.root, "me")
        text = build_monthly_report(profile, self.root, "me")
        self.assertIn("Mood", text)


# ---------------------------------------------------------------------------
# FHIR import tests
# ---------------------------------------------------------------------------

class FHIRTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1985-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write_fhir(self, data: dict) -> Path:
        p = self.root / "test.json"
        p.write_text(json.dumps(data))
        return p

    def _bundle(self, resources: list) -> dict:
        return {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [{"resource": r} for r in resources],
        }

    def test_condition_imported(self):
        fhir = self._bundle([{
            "resourceType": "Condition",
            "code": {"coding": [{"display": "Type 2 Diabetes"}], "text": "Type 2 Diabetes"},
            "clinicalStatus": {"coding": [{"code": "active"}]},
        }])
        counts = import_fhir_file(self.root, "me", self._write_fhir(fhir))
        self.assertEqual(counts.get("conditions"), 1)
        profile = load_profile(self.root, "me")
        names = [c["name"].lower() for c in profile.get("conditions", [])]
        self.assertTrue(any("diabetes" in n for n in names))

    def test_medication_imported(self):
        fhir = self._bundle([{
            "resourceType": "MedicationRequest",
            "status": "active",
            "medicationCodeableConcept": {"text": "Metformin 500mg"},
            "dosageInstruction": [],
        }])
        counts = import_fhir_file(self.root, "me", self._write_fhir(fhir))
        self.assertEqual(counts.get("medications"), 1)

    def test_allergy_imported(self):
        fhir = self._bundle([{
            "resourceType": "AllergyIntolerance",
            "code": {"text": "Penicillin"},
            "reaction": [{"manifestation": [{"text": "rash"}]}],
        }])
        counts = import_fhir_file(self.root, "me", self._write_fhir(fhir))
        self.assertEqual(counts.get("allergies"), 1)

    def test_duplicate_condition_not_duplicated(self):
        fhir = self._bundle([{
            "resourceType": "Condition",
            "code": {"text": "Hypothyroidism"},
            "clinicalStatus": {"coding": [{"code": "active"}]},
        }])
        path = self._write_fhir(fhir)
        import_fhir_file(self.root, "me", path)
        import_fhir_file(self.root, "me", path)
        profile = load_profile(self.root, "me")
        hypo = [c for c in profile.get("conditions", []) if "hypothyroid" in c["name"].lower()]
        self.assertEqual(len(hypo), 1)

    def test_is_fhir_file_detects_bundle(self):
        fhir = {"resourceType": "Bundle", "entry": []}
        p = self.root / "fhir.json"
        p.write_text(json.dumps(fhir))
        self.assertTrue(is_fhir_file(p))

    def test_is_fhir_file_rejects_other_json(self):
        p = self.root / "other.json"
        p.write_text(json.dumps({"data": {"metrics": []}}))
        self.assertFalse(is_fhir_file(p))


# ---------------------------------------------------------------------------
# Mental health tests
# ---------------------------------------------------------------------------

class MentalHealthTests(unittest.TestCase):
    def _checkins(self, n: int, mood: float, energy: float = 7, sleep: float = 7) -> list:
        result = []
        for i in range(n):
            d = (date.today() - timedelta(days=i)).isoformat()
            result.append({"date": d, "mood": mood, "energy": energy, "sleep_hours": sleep})
        return result

    def test_phq2_low_on_good_mood(self):
        result = score_phq2_from_checkins(self._checkins(10, mood=8.5))
        self.assertEqual(result["interpretation"], "low")

    def test_phq2_high_on_very_low_mood(self):
        result = score_phq2_from_checkins(self._checkins(10, mood=2.0))
        self.assertIn(result["interpretation"], ("moderate", "high"))

    def test_phq2_insufficient_data(self):
        result = score_phq2_from_checkins(self._checkins(1, mood=5))
        self.assertTrue(result.get("insufficient_data"))

    def test_burnout_detected_on_low_scores(self):
        result = detect_burnout(self._checkins(14, mood=4.0, energy=3.5, sleep=5.5))
        self.assertIn(result["risk"], ("moderate", "high"))

    def test_burnout_none_on_good_scores(self):
        result = detect_burnout(self._checkins(14, mood=8.0, energy=8.0, sleep=7.5))
        self.assertEqual(result["risk"], "none")

    def test_burnout_unknown_insufficient_data(self):
        result = detect_burnout(self._checkins(2, mood=4.0, energy=3.0))
        self.assertEqual(result["risk"], "unknown")

    def test_report_renders_without_error(self):
        profile = {"daily_checkins": self._checkins(10, mood=7)}
        text = build_mental_health_report(profile)
        self.assertIn("Mental Health", text)

    def test_report_low_data_message(self):
        text = build_mental_health_report({"daily_checkins": []})
        self.assertIn("Not enough", text)


# ---------------------------------------------------------------------------
# CLI wiring tests
# ---------------------------------------------------------------------------

class CLIWiringV22Tests(unittest.TestCase):
    def test_v22_subcommands_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        for cmd in [
            "check-interactions",
            "side-effects",
            "monthly-report",
            "import-fhir",
            "mental-health",
            "lab-range",
        ]:
            self.assertIn(cmd, choices, f"missing CLI command: {cmd}")


if __name__ == "__main__":
    unittest.main()
