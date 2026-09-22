"""Regression test: an ambiguous "abnormal" flag on a low-only marker used to
silently default to "high" and drop the result entirely, since "high" isn't
in that marker's knowledge dict (e.g. HDL only defines "low").
"""

import unittest

from scripts.lab_actions import actions_for_lab, _direction_for_marker


class DirectionForMarkerTests(unittest.TestCase):
    def test_abnormal_on_low_only_marker_resolves_to_low(self):
        self.assertEqual(_direction_for_marker("abnormal", {"low"}), "low")

    def test_abnormal_on_high_only_marker_resolves_to_high(self):
        self.assertEqual(_direction_for_marker("abnormal", {"high"}), "high")

    def test_abnormal_on_dual_direction_marker_is_unresolvable(self):
        # can't safely guess which direction -- must not silently assume "high"
        self.assertIsNone(_direction_for_marker("abnormal", {"high", "low"}))

    def test_explicit_high_and_low_still_work(self):
        self.assertEqual(_direction_for_marker("high", {"high", "low"}), "high")
        self.assertEqual(_direction_for_marker("low", {"high", "low"}), "low")


class ActionsForLowOnlyMarkerTests(unittest.TestCase):
    def test_low_hdl_flagged_abnormal_still_produces_actions(self):
        test = {"name": "HDL", "value": 32, "unit": "mg/dL", "flag": "abnormal", "date": "2025-06-01"}
        result = actions_for_lab(test)
        self.assertIsNotNone(result, "low HDL flagged 'abnormal' was silently dropped")
        self.assertEqual(result["direction"], "low")


if __name__ == "__main__":
    unittest.main()
