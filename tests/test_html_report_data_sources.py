"""Regression tests: the HTML dashboard's weight chart, lab chart, and output
path all silently used the wrong data source / location before this fix.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import (
    ensure_person,
    html_dashboard_path,
    load_profile,
    record_weight,
    save_profile,
)
from scripts.html_report import write_html_report


class _WS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1", "Test")

    def tearDown(self):
        shutil.rmtree(self.tmp)


class DashboardDataSourceTests(_WS):
    def test_weight_from_sqlite_appears_in_dashboard(self):
        record_weight(self.root, "p1", "2026-09-01", 78.0, "kg", "test")
        record_weight(self.root, "p1", "2026-09-15", 77.5, "kg", "test")
        profile = load_profile(self.root, "p1")
        path = write_html_report(self.root, "p1", profile)
        html = path.read_text()
        self.assertIn("77.5", html)

    def test_recent_tests_appear_as_lab_data(self):
        profile = load_profile(self.root, "p1")
        profile["recent_tests"] = [
            {"name": "TSH", "value": 1.8, "unit": "mIU/L", "date": "2026-09-01"},
        ]
        save_profile(self.root, "p1", profile)
        profile = load_profile(self.root, "p1")
        path = write_html_report(self.root, "p1", profile)
        html = path.read_text()
        self.assertIn("TSH", html)

    def test_output_path_matches_canonical_html_dashboard_path(self):
        profile = load_profile(self.root, "p1")
        path = write_html_report(self.root, "p1", profile)
        self.assertEqual(path, html_dashboard_path(self.root, "p1"))


if __name__ == "__main__":
    unittest.main()
