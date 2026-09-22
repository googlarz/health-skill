"""Regression tests for the consolidated parse_date() in care_workspace.py.

Before this, 7 modules each defined their own _parse_date, and two had already
drifted to accept more formats than the other five (connections.py, preventive.py
accepted "%Y/%m/%d"; preventive.py alone also accepted "%m/%d/%Y"). Every module
must now behave like the superset.
"""

import unittest
from datetime import date

from scripts.care_workspace import parse_date


class ParseDateTests(unittest.TestCase):
    def test_iso_format(self):
        self.assertEqual(parse_date("2025-06-01"), date(2025, 6, 1))

    def test_slash_ymd_format(self):
        self.assertEqual(parse_date("2025/06/01"), date(2025, 6, 1))

    def test_slash_mdy_format(self):
        self.assertEqual(parse_date("06/01/2025"), date(2025, 6, 1))

    def test_iso_datetime_truncated(self):
        self.assertEqual(parse_date("2025-06-01T10:30:00"), date(2025, 6, 1))

    def test_none_returns_none(self):
        self.assertIsNone(parse_date(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_date(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_date("not a date"))

    def test_every_module_uses_the_shared_function(self):
        import scripts.connections as connections
        import scripts.goals as goals
        import scripts.forecasting as forecasting
        import scripts.nudges as nudges
        import scripts.greeting as greeting
        import scripts.preventive as preventive
        import scripts.recap as recap

        for mod in (connections, goals, forecasting, nudges, greeting, preventive, recap):
            self.assertIs(
                mod._parse_date, parse_date,
                f"{mod.__name__}._parse_date is not the shared care_workspace.parse_date",
            )


if __name__ == "__main__":
    unittest.main()
