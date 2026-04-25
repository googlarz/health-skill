"""Tests for v2.5/v2.6 features: pharmacogenomics, appointments, post-visit, men's health, CLI wiring."""

import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.commands import build_parser
from scripts.appointments import (
    add_appointment,
    build_pre_visit_brief,
    get_upcoming_appointments,
    list_appointments,
    write_appointment_alerts,
)
from scripts.post_visit import extract_visit_data, merge_visit_data, write_post_visit_summary
from scripts.mens_health import (
    build_mens_health_report,
    interpret_psa,
    score_testosterone_symptoms,
)
from scripts.pharmacogenomics import (
    render_pgx_report as build_pgx_report,
    call_all_phenotypes,
    pgx_drug_alerts,
)


# ---------------------------------------------------------------------------
# Appointment tests
# ---------------------------------------------------------------------------

class AppointmentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1980-01-01", "male")
        self.profile = load_profile(self.root, "me")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _future(self, days: int) -> str:
        return (date.today() + timedelta(days=days)).isoformat()

    def test_add_appointment(self):
        add_appointment(self.profile, self._future(7), "cardiology", "annual check")
        self.assertEqual(len(self.profile["appointments"]), 1)
        self.assertEqual(self.profile["appointments"][0]["specialty"], "cardiology")

    def test_get_upcoming_filters_by_window(self):
        add_appointment(self.profile, self._future(5), "GP")
        add_appointment(self.profile, self._future(40), "dermatology")
        upcoming = get_upcoming_appointments(self.profile, days_ahead=30)
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["specialty"], "GP")

    def test_get_upcoming_excludes_past(self):
        add_appointment(self.profile, (date.today() - timedelta(days=1)).isoformat(), "GP")
        upcoming = get_upcoming_appointments(self.profile, days_ahead=30)
        self.assertEqual(len(upcoming), 0)

    def test_list_appointments_sorted(self):
        add_appointment(self.profile, self._future(10), "derm")
        add_appointment(self.profile, self._future(3), "GP")
        listed = list_appointments(self.profile)
        self.assertLess(listed[0]["date"], listed[1]["date"])

    def test_write_appointment_alerts_near_appointment(self):
        add_appointment(self.profile, self._future(3), "cardiology", "stress test")
        alerts = write_appointment_alerts(self.profile)
        self.assertEqual(len(alerts), 1)
        self.assertIn("cardiology", alerts[0]["message"].lower())

    def test_write_appointment_alerts_empty_when_none_soon(self):
        add_appointment(self.profile, self._future(30), "cardiology")
        alerts = write_appointment_alerts(self.profile)
        self.assertEqual(len(alerts), 0)

    def test_pre_visit_brief_renders(self):
        appt = {"date": self._future(5), "specialty": "cardiology", "reason": "chest pain"}
        self.profile["conditions"] = [{"name": "Hypertension"}]
        self.profile["medications"] = [{"name": "lisinopril", "dose": "10mg"}]
        text = build_pre_visit_brief(self.profile, appt)
        self.assertIn("Pre-Visit Brief", text)
        self.assertIn("Hypertension", text)
        self.assertIn("lisinopril", text)

    def test_pre_visit_includes_cardio_questions(self):
        appt = {"date": self._future(5), "specialty": "cardiology", "reason": ""}
        text = build_pre_visit_brief(self.profile, appt)
        self.assertIn("cardiovascular", text.lower())


# ---------------------------------------------------------------------------
# Post-visit tests
# ---------------------------------------------------------------------------

class PostVisitTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1980-01-01", "male")
        self.profile = load_profile(self.root, "me")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_extract_new_diagnosis(self):
        notes = "Patient diagnosed with Type 2 Diabetes. Follow-up in 3 months."
        data = extract_visit_data(notes)
        self.assertTrue(any("diabetes" in c.lower() for c in data["new_conditions"]))

    def test_extract_new_medication(self):
        notes = "Starting metformin 500mg twice daily for blood sugar control."
        data = extract_visit_data(notes)
        self.assertTrue(any("metformin" in m.lower() for m in data["new_medications"]))

    def test_extract_follow_up(self):
        notes = "Follow-up in 3 months. Repeat HbA1c at that time."
        data = extract_visit_data(notes)
        self.assertIn("3", data.get("follow_up_interval", ""))

    def test_extract_referral(self):
        notes = "Referred to endocrinologist for further management."
        data = extract_visit_data(notes)
        self.assertTrue(any("endocrinologist" in r.lower() for r in data["referrals"]))

    def test_merge_adds_condition(self):
        notes = "Diagnosed with hypothyroidism."
        data = extract_visit_data(notes)
        counts = merge_visit_data(self.profile, data)
        self.assertGreater(counts.get("conditions", 0), 0)
        names = [c["name"].lower() for c in self.profile["conditions"]]
        self.assertTrue(any("hypothyroid" in n for n in names))

    def test_merge_no_duplicate_condition(self):
        self.profile["conditions"] = [{"name": "Hypothyroidism"}]
        notes = "Diagnosed with hypothyroidism."
        data = extract_visit_data(notes)
        merge_visit_data(self.profile, data)
        hypo = [c for c in self.profile["conditions"] if "hypothyroid" in c["name"].lower()]
        self.assertEqual(len(hypo), 1)

    def test_merge_records_visit(self):
        data = extract_visit_data("Annual check. All good. Follow-up in 12 months.")
        merge_visit_data(self.profile, data)
        self.assertEqual(len(self.profile.get("visit_history", [])), 1)

    def test_summary_renders(self):
        notes = "Diagnosed with hypertension. Starting lisinopril 10mg. Follow-up in 3 months."
        data = extract_visit_data(notes)
        text = write_post_visit_summary(self.profile, data)
        self.assertIn("Post-Visit Summary", text)


# ---------------------------------------------------------------------------
# Men's health tests
# ---------------------------------------------------------------------------

class MensHealthTests(unittest.TestCase):
    def _profile(self, age_years: int = 50, conditions=None, meds=None) -> dict:
        dob = (date.today() - timedelta(days=age_years * 365)).isoformat()
        return {
            "date_of_birth": dob,
            "sex": "male",
            "conditions": [{"name": c} for c in (conditions or [])],
            "medications": [{"name": m} for m in (meds or [])],
            "daily_checkins": [],
            "lab_results": [],
            "notes": [],
        }

    def test_report_renders(self):
        text = build_mens_health_report(self._profile(50))
        self.assertIn("Men's Health Report", text)

    def test_report_includes_psa_section_for_50(self):
        text = build_mens_health_report(self._profile(50))
        self.assertIn("PSA", text)

    def test_report_no_psa_section_for_35(self):
        text = build_mens_health_report(self._profile(35))
        self.assertNotIn("PSA & Prostate", text)

    def test_interpret_psa_normal(self):
        result = interpret_psa(1.5, age=55)
        self.assertEqual(result["flags"], [])
        self.assertIn("normal", result["recommendation"].lower())

    def test_interpret_psa_elevated(self):
        result = interpret_psa(5.0, age=55)
        self.assertIn("elevated_for_age", result["flags"])

    def test_interpret_psa_velocity_flag(self):
        result = interpret_psa(3.0, age=60, prior_psa=1.5, prior_psa_years_ago=1.0)
        self.assertIn("rising_velocity", result["flags"])

    def test_testosterone_symptoms_high_score(self):
        profile = self._profile(45)
        profile["daily_checkins"] = [
            {"date": (date.today() - timedelta(days=i)).isoformat(),
             "mood": 3.0, "energy": 2.5, "pain": 2, "sleep_hours": 6}
            for i in range(14)
        ]
        result = score_testosterone_symptoms(profile)
        self.assertGreater(result["score"], 0)
        self.assertIn("fatigue", result["symptoms_found"])

    def test_testosterone_symptoms_none_on_good_scores(self):
        profile = self._profile(45)
        profile["daily_checkins"] = [
            {"date": (date.today() - timedelta(days=i)).isoformat(),
             "mood": 8.0, "energy": 8.0, "pain": 1, "sleep_hours": 7.5}
            for i in range(14)
        ]
        result = score_testosterone_symptoms(profile)
        self.assertEqual(result["score"], 0)

    def test_ed_flags_cardiovascular(self):
        profile = self._profile(50, conditions=["erectile dysfunction"])
        text = build_mens_health_report(profile)
        self.assertIn("cardiovascular", text.lower())


# ---------------------------------------------------------------------------
# Pharmacogenomics tests
# ---------------------------------------------------------------------------

class PGXTests(unittest.TestCase):
    def _phenotypes(self, **kwargs) -> dict:
        defaults = {
            "CYP2C19": {"phenotype": "normal_metaboliser", "label": "Normal metaboliser", "alleles": "*1/*1"},
            "CYP2D6": {"phenotype": "normal_metaboliser", "label": "Normal metaboliser", "alleles": "*1/*1"},
            "CYP2C9": {"phenotype": "normal_metaboliser", "label": "Normal metaboliser", "alleles": "*1/*1"},
            "SLCO1B1": {"phenotype": "normal_function", "label": "Normal function", "alleles": "T/T"},
            "VKORC1": {"phenotype": "normal_sensitivity", "label": "Normal sensitivity", "alleles": "G/G"},
            "MTHFR": {"phenotype": "normal", "label": "Normal", "alleles": "C/C"},
            "DPYD": {"phenotype": "normal_metaboliser", "label": "Normal metaboliser", "alleles": "normal/normal"},
        }
        for k, v in kwargs.items():
            if "label" not in v:
                v["label"] = v.get("phenotype", "").replace("_", " ").title()
            defaults[k] = v
        return defaults

    def test_clopidogrel_pm_alert(self):
        phenotypes = self._phenotypes(CYP2C19={"phenotype": "poor_metaboliser", "alleles": "*2/*2"})
        alerts = pgx_drug_alerts(phenotypes, [{"name": "clopidogrel"}])
        self.assertTrue(any(a["severity"] == "critical" for a in alerts))

    def test_no_alert_on_normal(self):
        phenotypes = self._phenotypes()
        alerts = pgx_drug_alerts(phenotypes, [{"name": "clopidogrel"}])
        self.assertEqual(alerts, [])

    def test_statin_slco1b1_alert(self):
        phenotypes = self._phenotypes(SLCO1B1={"phenotype": "intermediate_function", "alleles": "T/C"})
        alerts = pgx_drug_alerts(phenotypes, [{"name": "simvastatin"}])
        self.assertTrue(any(a["severity"] in ("major", "critical") for a in alerts))

    def test_dpyd_fluorouracil_alert(self):
        phenotypes = self._phenotypes(DPYD={"phenotype": "poor_metaboliser", "alleles": "*2A/*2A"})
        alerts = pgx_drug_alerts(phenotypes, [{"name": "fluorouracil"}])
        self.assertTrue(any(a["severity"] == "critical" for a in alerts))

    def test_pgx_report_renders(self):
        phenotypes = self._phenotypes()
        text = build_pgx_report(phenotypes, [], variants_found=0)
        self.assertIn("Pharmacogenomics", text)

    def test_pgx_report_includes_alert(self):
        phenotypes = self._phenotypes(CYP2C19={"phenotype": "poor_metaboliser", "alleles": "*2/*2"})
        alerts = pgx_drug_alerts(phenotypes, [{"name": "clopidogrel"}])
        text = build_pgx_report(phenotypes, alerts, variants_found=2)
        self.assertIn("clopidogrel", text.lower())


# ---------------------------------------------------------------------------
# CLI wiring tests
# ---------------------------------------------------------------------------

class CLIWiringV25Tests(unittest.TestCase):
    def test_new_subcommands_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        for cmd in [
            "import-pgx",
            "pgx-report",
            "add-appointment",
            "pre-visit",
            "post-visit",
            "mens-health",
        ]:
            self.assertIn(cmd, choices, f"missing CLI command: {cmd}")


if __name__ == "__main__":
    unittest.main()
