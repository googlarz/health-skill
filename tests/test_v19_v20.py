"""Tests for v1.9 + v2.0 features."""

import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.commands import build_parser
from scripts.decisions import (hrt_decision, screening_intensity_decision,
                               statin_decision)
from scripts.forecasting import forecast_marker, forecast_labs
from scripts.household import (add_member, add_relationship,
                               cascade_family_history, load_household)
from scripts.lab_actions import actions_for_lab, build_actions
from scripts.nutrition import parse_meal


class ForecastingTests(unittest.TestCase):
    def test_insufficient_data(self):
        f = forecast_marker([(date(2024, 1, 1), 100.0)])
        self.assertTrue(f.get("insufficient_data"))

    def test_clear_downward_trend(self):
        series = [
            (date(2024, 1, 1), 200.0),
            (date(2024, 4, 1), 180.0),
            (date(2024, 7, 1), 160.0),
            (date(2024, 10, 1), 140.0),
        ]
        f = forecast_marker(series, target_value=130.0)
        self.assertLess(f["slope_per_day"], 0)
        self.assertIn(f["confidence"], ("medium", "high"))

    def test_lab_forecast_picks_known_markers(self):
        profile = {
            "recent_tests": [
                {"name": "LDL", "value": 188, "unit": "mg/dL", "date": "2024-01-15"},
                {"name": "LDL", "value": 162, "unit": "mg/dL", "date": "2024-08-10"},
                {"name": "LDL", "value": 141, "unit": "mg/dL", "date": "2025-03-20"},
            ]
        }
        f = forecast_labs(profile)
        self.assertIn("LDL", f)
        self.assertLess(f["LDL"]["slope_per_year"], 0)


class LabActionsTests(unittest.TestCase):
    def test_high_ldl_yields_action(self):
        a = actions_for_lab({"name": "LDL", "value": 165, "flag": "high", "date": "2025-03-20"})
        self.assertIsNotNone(a)
        assert a is not None  # mypy
        self.assertEqual(a["marker"], "LDL")
        self.assertGreater(len(a["questions"]), 0)
        self.assertIn("statin", " ".join(a["questions"]).lower())

    def test_normal_yields_no_action(self):
        a = actions_for_lab({"name": "LDL", "value": 90, "flag": "normal", "date": "2025-03-20"})
        self.assertIsNone(a)

    def test_unknown_marker_yields_no_action(self):
        a = actions_for_lab({"name": "BogusMarker", "value": 99, "flag": "high", "date": "2025-03-20"})
        self.assertIsNone(a)

    def test_build_actions_picks_latest_per_marker(self):
        profile = {
            "recent_tests": [
                {"name": "LDL", "value": 188, "flag": "high", "date": "2024-01-15"},
                {"name": "LDL", "value": 141, "flag": "high", "date": "2025-03-20"},
            ]
        }
        actions = build_actions(profile)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["value"], 141)


class NutritionTests(unittest.TestCase):
    def test_parse_meal_extracts_macros(self):
        r = parse_meal("chicken breast 200g, rice 1 cup, broccoli, olive oil")
        self.assertGreater(r["kcal"], 400)
        self.assertGreater(r["protein"], 40)
        self.assertEqual(r["unmatched_count"], 0)

    def test_parse_meal_handles_unknown_items(self):
        r = parse_meal("chicken breast 200g, mystery food xyz")
        self.assertGreater(r["matched_count"], 0)
        self.assertGreater(r["unmatched_count"], 0)

    def test_empty_meal_returns_zero(self):
        r = parse_meal("")
        self.assertEqual(r["kcal"], 0)


class DecisionsTests(unittest.TestCase):
    def test_hrt_applicable_for_female(self):
        d = hrt_decision({
            "date_of_birth": "1975-01-01",
            "sex": "female",
            "daily_checkins": [{"notes": "hot flashes at night, terrible sleep"}],
        })
        self.assertTrue(d["applicable"])
        self.assertIn("hot_flashes", d["symptoms_present"])
        self.assertGreater(len(d["questions"]), 0)

    def test_hrt_not_applicable_for_male(self):
        d = hrt_decision({"date_of_birth": "1975-01-01", "sex": "male"})
        self.assertFalse(d["applicable"])

    def test_statin_with_diabetes_and_age(self):
        d = statin_decision({
            "date_of_birth": "1970-01-01",
            "sex": "female",
            "conditions": [{"name": "type 2 diabetes"}],
            "recent_tests": [{"name": "LDL", "value": 145, "date": "2025-01-01"}],
        })
        self.assertEqual(d["ldl"], 145.0)
        self.assertTrue(d["has_diabetes"])
        self.assertTrue(any("diabetes" in p.lower() for p in d["pros"]))

    def test_screening_with_breast_cancer_history(self):
        d = screening_intensity_decision({
            "date_of_birth": "1985-01-01",
            "sex": "female",
            "family_history": [{"relation": "mother", "condition": "breast cancer", "age_at_diagnosis": 48}],
        })
        self.assertTrue(any("breast" in n.lower() for n in d["notes"]))


class HouseholdTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "anna", "Anna", "1985-01-01", "female")
        ensure_person(self.root, "mom", "Sarah", "1960-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_add_member_persists(self):
        add_member(self.root, "self", "Anna", "anna", "1985-01-01", "female")
        hh = load_household(self.root)
        self.assertEqual(len(hh["members"]), 1)
        self.assertEqual(hh["members"][0]["id"], "self")

    def test_cascade_propagates_breast_cancer(self):
        # Set up: mom has breast cancer in her profile
        mom_profile = load_profile(self.root, "mom")
        mom_profile["conditions"] = [
            {"name": "breast cancer", "diagnosed_date": "2010-06-01"}
        ]
        save_profile(self.root, "mom", mom_profile)

        add_member(self.root, "self", "Anna", "anna", "1985-01-01", "female")
        add_member(self.root, "mom", "Sarah", "mom", "1960-01-01", "female")
        add_relationship(self.root, "self", "mom", "mother")

        summary = cascade_family_history(self.root)
        self.assertGreaterEqual(summary["entries_added"], 1)

        anna_profile = load_profile(self.root, "anna")
        fh = anna_profile.get("family_history", [])
        breast = [f for f in fh if "breast" in f.get("condition", "").lower()]
        self.assertEqual(len(breast), 1)
        self.assertEqual(breast[0]["relation"], "mother")


class CLIWiringTests(unittest.TestCase):
    def test_v19_v20_subcommands_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        for cmd in [
            "forecast", "lab-actions", "log-meal", "nutrition",
            "decide", "sync-wearable",
            "household-add-member", "household-add-relationship",
            "household-cascade", "household-dashboard",
        ]:
            self.assertIn(cmd, choices, f"missing {cmd}")


if __name__ == "__main__":
    unittest.main()
