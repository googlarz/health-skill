"""Tests for v1.8 longevity companion features."""

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile
from scripts.checkins import parse_checkin
from scripts.commands import build_parser
from scripts.goals import add_goal, current_value, progress_pct
from scripts.nudges import compute_nudges
from scripts.preventive import compute_due_screenings, family_history_adjustments
from scripts.providers import add_provider
from scripts.recap import build_recap
from scripts.triage import assess


class ShorthandCheckinTests(unittest.TestCase):
    def test_shorthand_full(self):
        r = parse_checkin("m7 s7.5 e6 p3")
        self.assertEqual(r.get("mood"), 7)
        self.assertEqual(r.get("sleep_hours"), 7.5)
        self.assertEqual(r.get("energy"), 6)
        self.assertEqual(r.get("pain_severity"), 3)

    def test_colon_mood(self):
        r = parse_checkin(":8")
        self.assertEqual(r.get("mood"), 8)

    def test_weight_kg(self):
        r = parse_checkin("w72.5")
        self.assertEqual(r.get("weight_kg"), 72.5)


class NudgesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "", "Test", "1980-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_nudges_returns_list_of_dicts(self):
        out = compute_nudges(self.root, "")
        self.assertIsInstance(out, list)
        for n in out:
            self.assertIn("priority", n)
            self.assertIn("title", n)


class GoalsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "", "Test", "1980-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_add_goal_persists(self):
        g = add_goal(self.root, "", title="LDL <130", metric="ldl", target=130.0)
        self.assertEqual(g["title"], "LDL <130")
        self.assertEqual(g["metric"], "ldl")
        profile = load_profile(self.root, "")
        self.assertEqual(len(profile.get("goals", [])), 1)

    def test_unknown_metric_rejected(self):
        with self.assertRaises(ValueError):
            add_goal(self.root, "", title="bogus", metric="not_a_metric", target=1.0)

    def test_progress_pct_no_baseline(self):
        self.assertIsNone(progress_pct({"target": 100}, 90))


class ProvidersTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "", "Test", "1980-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_role_alias_expansion(self):
        p = add_provider(self.root, "", name="Dr Smith", role="pcp")
        self.assertEqual(p["role"], "Primary Care Physician")
        p2 = add_provider(self.root, "", name="Dr Jones", role="cardio")
        self.assertEqual(p2["role"], "Cardiologist")


class TriageTests(unittest.TestCase):
    def test_chest_pain_red_flag(self):
        a = assess({"q1": "chest pain with pressure radiating to jaw", "q2": "30 min"})
        self.assertEqual(a["band"], "Emergency now")
        self.assertTrue(a["red_flags"])

    def test_low_severity_education(self):
        a = assess({"q1": "mild knee soreness", "q2": "few days", "q3": "1/10"})
        self.assertEqual(a["band"], "Education only")

    def test_postmenopausal_bleeding_emergency(self):
        a = assess({"q1": "postmenopausal bleeding"})
        self.assertEqual(a["band"], "Emergency now")


class FamilyHistoryScreeningTests(unittest.TestCase):
    def test_breast_cancer_pulls_mammogram_forward(self):
        profile = {
            "date_of_birth": "1985-01-01",
            "sex": "female",
            "family_history": [
                {"relation": "mother", "condition": "breast cancer", "age_at_diagnosis": 48}
            ],
        }
        adj = family_history_adjustments(profile)
        self.assertIn("mammogram", adj)
        # Should be 38 (48-10), not the default 35
        self.assertLessEqual(adj["mammogram"]["age_start_override"], 40)

    def test_colon_cancer_pulls_colonoscopy(self):
        profile = {
            "date_of_birth": "1985-01-01",
            "sex": "any",
            "family_history": [
                {"relation": "father", "condition": "colon cancer", "age_at_diagnosis": 55}
            ],
        }
        adj = family_history_adjustments(profile)
        self.assertIn("colonoscopy", adj)


class WeeklyRecapTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "", "Test", "1980-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_recap_has_required_sections(self):
        text = build_recap(self.root, "", days=7)
        self.assertIn("# Weekly Recap", text)
        self.assertIn("How you've felt", text)
        self.assertIn("Training", text)
        self.assertIn("Weight", text)
        self.assertIn("One thing to action next", text)


class CLIWiringTests(unittest.TestCase):
    def test_all_v18_subcommands_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        for cmd in [
            "nudges", "weekly-recap", "add-goal", "goals",
            "add-provider", "providers", "import-wearable", "triage",
        ]:
            self.assertIn(cmd, choices)


if __name__ == "__main__":
    unittest.main()
