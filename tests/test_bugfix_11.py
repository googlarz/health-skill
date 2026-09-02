"""Regression tests for the 11-bug fix batch (post-v2.4.0).

One test class per bug; each test fails on the pre-fix code.
"""

import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.pharmacogenomics import call_all_phenotypes
from scripts.interactions import check_interactions
from scripts.lab_ranges import flag_lab_value, personalised_range
from scripts.cycles import parse_cycle_event
from scripts.extraction import extract_document_date
from scripts.nudges import compute_nudges
from scripts.appointments import build_pre_visit_brief


class _WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1", "Test")

    def tearDown(self):
        shutil.rmtree(self.tmp)


# 1. appointments survived save_profile (was stripped by normalize_profile)
class AppointmentsPersistTests(_WorkspaceCase):
    def test_appointment_survives_save_load(self):
        p = load_profile(self.root, "p1")
        p.setdefault("appointments", []).append(
            {"date": "2027-01-15", "specialty": "cardiology"}
        )
        save_profile(self.root, "p1", p)
        reloaded = load_profile(self.root, "p1")
        self.assertEqual(len(reloaded.get("appointments", [])), 1)
        self.assertEqual(reloaded["appointments"][0]["specialty"], "cardiology")


# 2. pharmacogenomics survived save_profile (was stripped by normalize_profile)
class PgxPersistTests(_WorkspaceCase):
    def test_pgx_data_survives_save_load(self):
        p = load_profile(self.root, "p1")
        p["pharmacogenomics"] = {"phenotypes": {"CYP2C19": {"phenotype": "poor_metaboliser"}},
                                 "variants_found": 3}
        save_profile(self.root, "p1", p)
        reloaded = load_profile(self.root, "p1")
        self.assertEqual(reloaded.get("pharmacogenomics", {}).get("variants_found"), 3)


# 3. pain readers use pain_severity (the key parse_checkin actually writes)
class PainKeyTests(_WorkspaceCase):
    def test_high_pain_nudge_fires_on_canonical_key(self):
        p = load_profile(self.root, "p1")
        p["daily_checkins"] = [
            {"date": str(date.today() - timedelta(days=i)), "pain_severity": 8,
             "mood": 6, "energy": 6, "sleep_hours": 7}
            for i in range(6)
        ]
        save_profile(self.root, "p1", p)
        titles = [n["title"].lower() for n in compute_nudges(self.root, "p1")]
        self.assertTrue(any("pain" in t for t in titles),
                        f"high-pain nudge missing from: {titles}")


# 4. overdue follow-up nudge reads the singular follow_up key
class FollowUpKeyTests(_WorkspaceCase):
    def test_overdue_follow_up_nudge_fires(self):
        p = load_profile(self.root, "p1")
        p["follow_up"] = [{"task": "recheck BP", "due_date": "2020-01-01", "status": "open"}]
        save_profile(self.root, "p1", p)
        titles = [n["title"].lower() for n in compute_nudges(self.root, "p1")]
        self.assertTrue(any("overdue" in t or "follow" in t for t in titles),
                        f"overdue follow-up nudge missing from: {titles}")


# 5. INR has a base range; dangerous INR on warfarin is not "normal"
class INRRangeTests(unittest.TestCase):
    def test_inr_5_on_warfarin_flagged(self):
        profile = {"medications": [{"name": "warfarin"}], "conditions": []}
        self.assertNotEqual(flag_lab_value("INR", 5.0, profile), "normal")

    def test_warfarin_target_range_applied(self):
        profile = {"medications": [{"name": "warfarin"}], "conditions": []}
        r = personalised_range("INR", profile)
        self.assertEqual(r.get("low"), 2.0)
        self.assertEqual(r.get("high"), 3.0)

    def test_inr_in_range_on_warfarin_normal(self):
        profile = {"medications": [{"name": "warfarin"}], "conditions": []}
        self.assertEqual(flag_lab_value("INR", 2.5, profile), "normal")


# 6. CYP2C19 one LoF + one GoF allele (*2/*17) = intermediate, never normal
class CYP2C19Tests(unittest.TestCase):
    def test_lof_plus_gof_is_intermediate(self):
        variants = {
            "rs4244285": "AG",   # *2 het (A = LoF allele)
            "rs12248560": "CT",  # *17 het (T = GoF allele)
        }
        pheno = call_all_phenotypes(variants)["CYP2C19"]["phenotype"]
        self.assertEqual(pheno, "intermediate_metaboliser")


# 7. drug-class keywords no longer false-match unrelated drugs
class MedMatcherTests(unittest.TestCase):
    def _profile(self, meds):
        return {"medications": [{"name": m} for m in meds],
                "supplements": [], "conditions": [], "daily_checkins": []}

    def test_nystatin_is_not_a_statin(self):
        alerts = check_interactions(self._profile(["nystatin", "clarithromycin"]))
        self.assertFalse(any("statin" in str(a.get("effect", "")).lower() for a in alerts),
                         f"false statin alert: {alerts}")

    def test_real_statin_still_matches(self):
        alerts = check_interactions(self._profile(["atorvastatin", "clarithromycin"]))
        self.assertTrue(any("statin" in str(a.get("effect", "")).lower() for a in alerts))

    def test_carbamazepine_is_not_an_arb(self):
        alerts = check_interactions(self._profile(["carbamazepine", "ibuprofen"]))
        self.assertEqual(alerts, [], f"false ARB/NSAID alert: {alerts}")

    def test_real_arb_still_matches(self):
        alerts = check_interactions(self._profile(["losartan", "ibuprofen"]))
        self.assertTrue(len(alerts) >= 1)

    def test_spironolactone_is_not_iron(self):
        alerts = check_interactions(self._profile(["levothyroxine", "spironolactone"]))
        self.assertFalse(any("absorption" in str(a.get("effect", "")).lower() for a in alerts),
                         f"false iron/levothyroxine alert: {alerts}")

    def test_real_iron_still_matches(self):
        alerts = check_interactions(self._profile(["levothyroxine", "iron supplement"]))
        self.assertTrue(len(alerts) >= 1)


# 8. "period ended ... started" is an ended event, not a new cycle start
class CycleParseTests(unittest.TestCase):
    def test_ended_with_incidental_started_word(self):
        ev = parse_cycle_event("period ended today, cramps started last night")
        self.assertEqual(ev["event_type"], "period_ended")

    def test_plain_start_still_works(self):
        ev = parse_cycle_event("started my period")
        self.assertEqual(ev["event_type"], "period_started")


# 9. pre-visit brief: allergies keyed by substance; labs come from recent_tests
class PreVisitBriefTests(unittest.TestCase):
    def test_allergy_substance_key_no_crash(self):
        profile = {
            "name": "Test", "conditions": [], "medications": [],
            "allergies": [{"substance": "penicillin", "reaction": "rash"}],
            "daily_checkins": [], "recent_tests": [], "follow_up": [],
        }
        brief = build_pre_visit_brief(profile, {"specialty": "cardiology", "date": "2027-01-15"})
        self.assertIn("penicillin", brief)

    def test_labs_render_from_recent_tests(self):
        recent = (date.today() - timedelta(days=30)).isoformat()
        profile = {
            "name": "Test", "conditions": [], "medications": [], "allergies": [],
            "daily_checkins": [], "follow_up": [],
            "recent_tests": [{"name": "LDL", "value": 155, "unit": "mg/dL", "date": recent}],
        }
        brief = build_pre_visit_brief(profile, {"specialty": "cardiology", "date": "2027-01-15"})
        self.assertIn("LDL", brief)


# 10. document date: "Birth Date" must not win over the real collection date
class DocumentDateTests(unittest.TestCase):
    def test_birth_date_not_used(self):
        text = "Patient: Jane Doe\nBirth Date: 01/15/1960\nDate Collected: 06/12/2025\n"
        self.assertEqual(extract_document_date(text), "2025-06-12")

    def test_bare_date_line_still_parsed(self):
        text = "Lab report\nDate: 06/12/2025\n"
        self.assertEqual(extract_document_date(text), "2025-06-12")


# 11. Apple sleep: asleep stages counted once, InBed/Awake not double-counted
class AppleSleepTests(_WorkspaceCase):
    def _xml(self, records: str) -> Path:
        p = self.root / "export.xml"
        p.write_text(f"<HealthData>{records}</HealthData>")
        return p

    def _rec(self, value, start, end):
        return (f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="{value}" '
                f'startDate="{start}" endDate="{end}" />')

    def test_overlapping_stages_not_double_counted(self):
        from scripts.wearable_import import import_wearable_file
        records = (
            self._rec("HKCategoryValueSleepAnalysisInBed", "2025-06-01 23:00:00 +0000", "2025-06-02 07:00:00 +0000")
            + self._rec("HKCategoryValueSleepAnalysisAsleepCore", "2025-06-01 23:30:00 +0000", "2025-06-02 03:00:00 +0000")
            + self._rec("HKCategoryValueSleepAnalysisAsleepREM", "2025-06-02 03:00:00 +0000", "2025-06-02 06:30:00 +0000")
            + self._rec("HKCategoryValueSleepAnalysisAwake", "2025-06-02 02:00:00 +0000", "2025-06-02 02:30:00 +0000")
        )
        import_wearable_file(self.root, "p1", self._xml(records))
        profile = load_profile(self.root, "p1")
        by_date = {c["date"]: c for c in profile.get("daily_checkins", [])}
        hours = sum(c.get("sleep_hours", 0) for c in by_date.values())
        # Asleep spans: 3.5h (night of 1st) + 3.5h (morning of 2nd) = 7h total,
        # never the ~15.5h the old sum-everything logic produced.
        self.assertLess(hours, 8.5, f"sleep overcounted: {hours}h")
        self.assertGreater(hours, 5.5, f"sleep undercounted: {hours}h")

    def test_inbed_only_export_falls_back(self):
        from scripts.wearable_import import import_wearable_file
        records = self._rec("HKCategoryValueSleepAnalysisInBed",
                            "2025-06-01 23:00:00 +0000", "2025-06-02 07:00:00 +0000")
        import_wearable_file(self.root, "p1", self._xml(records))
        profile = load_profile(self.root, "p1")
        hours = sum(c.get("sleep_hours", 0) for c in profile.get("daily_checkins", []))
        self.assertGreater(hours, 7.5)


if __name__ == "__main__":
    unittest.main()
