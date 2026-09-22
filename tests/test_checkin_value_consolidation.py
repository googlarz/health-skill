"""Regression tests for the shared checkin_value() accessor — the root-cause
fix for the pain/pain_severity key-mismatch bug that recurred independently
across 9 files in three separate bug-fix passes (Sept 2026).
"""

import unittest

from scripts.care_workspace import checkin_value


class CheckinValueTests(unittest.TestCase):
    def test_pain_resolves_to_pain_severity(self):
        self.assertEqual(checkin_value({"pain_severity": 8}, "pain"), 8)

    def test_sleep_resolves_to_sleep_hours(self):
        self.assertEqual(checkin_value({"sleep_hours": 6.5}, "sleep"), 6.5)

    def test_unaliased_field_passes_through(self):
        self.assertEqual(checkin_value({"mood": 7}, "mood"), 7)

    def test_missing_field_returns_none(self):
        self.assertIsNone(checkin_value({}, "pain"))

    def test_direct_key_not_used_for_aliased_field(self):
        # a stray "pain" key must NOT be read when "pain" is an alias —
        # the canonical key is "pain_severity"
        self.assertIsNone(checkin_value({"pain": 3}, "pain"))


class CheckinValueUsedByAllMigratedModules(unittest.TestCase):
    def test_modules_import_the_shared_accessor(self):
        import scripts.appointments as appointments
        import scripts.artifacts as artifacts
        import scripts.connections as connections
        import scripts.greeting as greeting
        import scripts.html_report as html_report
        import scripts.monthly_report as monthly_report
        import scripts.nudges as nudges
        import scripts.recap as recap
        import scripts.side_effects as side_effects

        for mod in (appointments, artifacts, connections, greeting, html_report,
                    monthly_report, nudges, recap, side_effects):
            self.assertIs(
                mod.checkin_value, checkin_value,
                f"{mod.__name__}.checkin_value is not the shared care_workspace.checkin_value",
            )


if __name__ == "__main__":
    unittest.main()
