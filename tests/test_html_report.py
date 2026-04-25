"""Tests for HTML dashboard generation."""

import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.commands import build_parser
from scripts.html_report import build_html_report, write_html_report


class HTMLReportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test User", "1985-06-15", "female")
        self.profile = load_profile(self.root, "me")
        # Add some realistic data
        self.profile["conditions"] = [{"name": "Hypothyroidism", "diagnosed": "2020-03-01"}]
        self.profile["medications"] = [
            {"name": "levothyroxine", "dose": "50mcg", "start_date": "2020-03-15", "active": True}
        ]
        self.profile["lab_results"] = [
            {"marker": "TSH", "value": 1.8, "unit": "mIU/L", "date": "2025-01-10"},
            {"marker": "LDL", "value": 95, "unit": "mg/dL", "date": "2025-01-10"},
        ]
        for i in range(30):
            d = (date.today() - timedelta(days=i)).isoformat()
            self.profile.setdefault("daily_checkins", []).append({
                "date": d, "mood": 7.0, "energy": 6.5, "pain": 2.0, "sleep_hours": 7.2
            })
        self.profile["weight_entries"] = [
            {"date": (date.today() - timedelta(days=i)).isoformat(), "value": 65.0 + i * 0.02, "unit": "kg"}
            for i in range(30)
        ]
        save_profile(self.root, "me", self.profile)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_html_renders_without_error(self):
        html = build_html_report(self.profile)
        self.assertIsInstance(html, str)
        self.assertGreater(len(html), 1000)

    def test_html_is_valid_html5(self):
        html = build_html_report(self.profile)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<html", html)
        self.assertIn("</html>", html)

    def test_html_includes_chartjs(self):
        html = build_html_report(self.profile)
        self.assertIn("chart.js", html.lower())

    def test_html_includes_person_name(self):
        html = build_html_report(self.profile)
        self.assertIn("Test User", html)

    def test_html_includes_conditions(self):
        html = build_html_report(self.profile)
        self.assertIn("Hypothyroidism", html)

    def test_html_includes_medication(self):
        html = build_html_report(self.profile)
        self.assertIn("levothyroxine", html)

    def test_html_includes_lab_data(self):
        html = build_html_report(self.profile)
        self.assertIn("TSH", html)
        self.assertIn("LDL", html)

    def test_html_includes_trend_chart(self):
        html = build_html_report(self.profile)
        self.assertIn("trendsChart", html)
        self.assertIn("Mood", html)

    def test_write_creates_file(self):
        out = write_html_report(self.root, "me", self.profile)
        self.assertTrue(out.exists())
        self.assertEqual(out.name, "HEALTH_DASHBOARD.html")
        content = out.read_text()
        self.assertIn("<!DOCTYPE html>", content)

    def test_empty_profile_renders_gracefully(self):
        empty = {"name": "Empty"}
        html = build_html_report(empty)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("No medications recorded", html)
        self.assertIn("No upcoming appointments", html)

    def test_kpi_cards_show_averages(self):
        html = build_html_report(self.profile)
        self.assertIn("30-day averages", html)

    def test_appointments_section_shows_upcoming(self):
        future = (date.today() + timedelta(days=5)).isoformat()
        self.profile["appointments"] = [
            {"date": future, "specialty": "endocrinology", "reason": "thyroid check"}
        ]
        html = build_html_report(self.profile)
        self.assertIn("endocrinology", html.lower())

    def test_cli_dashboard_command_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        self.assertIn("dashboard", choices)


if __name__ == "__main__":
    unittest.main()
