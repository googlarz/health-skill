"""Tests for v2.2.1 features: supplement-drug interactions, non-dipping BP nudge,
run metrics/run_summary, intervention tracker, CLI wiring."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.care_workspace import (
    ensure_metrics_db,
    ensure_person,
    intervention_status,
    load_profile,
    log_intervention,
    save_profile,
)
from scripts.commands import build_parser
from scripts.interactions import check_interactions, render_interactions_text
from scripts.nudges import compute_nudges
from scripts.training import run_summary


# ---------------------------------------------------------------------------
# Supplement-drug interaction tests
# ---------------------------------------------------------------------------

class SupplementDrugInteractionTests(unittest.TestCase):
    def _make_profile(self, medications, supplements):
        return {
            "medications": [{"name": m, "dose": "1x"} for m in medications],
            "supplements": [{"name": s} for s in supplements],
            "conditions": [],
            "daily_checkins": [],
            "recent_tests": [],
            "follow_ups": [],
        }

    def test_nattokinase_warfarin_major(self):
        profile = self._make_profile(["warfarin"], ["nattokinase"])
        alerts = check_interactions(profile)
        supp = [a for a in alerts if a.get("type") == "supplement-drug"]
        self.assertTrue(len(supp) >= 1)
        self.assertEqual(supp[0]["severity"], "major")

    def test_fish_oil_aspirin_moderate(self):
        profile = self._make_profile(["aspirin"], ["fish oil"])
        alerts = check_interactions(profile)
        supp = [a for a in alerts if a.get("type") == "supplement-drug"]
        self.assertTrue(len(supp) >= 1)
        self.assertEqual(supp[0]["severity"], "moderate")

    def test_vitamin_k2_warfarin_major(self):
        profile = self._make_profile(["warfarin"], ["vitamin k2"])
        alerts = check_interactions(profile)
        supp = [a for a in alerts if a.get("type") == "supplement-drug"]
        major = [a for a in supp if a["severity"] == "major"]
        self.assertTrue(len(major) >= 1)

    def test_no_false_positive_unrelated_supplement(self):
        profile = self._make_profile(["lisinopril"], ["vitamin d"])
        alerts = check_interactions(profile)
        supp = [a for a in alerts if a.get("type") == "supplement-drug"]
        self.assertEqual(supp, [])

    def test_render_shows_supplement_drug_label(self):
        profile = self._make_profile(["warfarin"], ["nattokinase"])
        text = render_interactions_text(profile)
        self.assertIn("Supplement", text)

    def test_no_supplements_field_no_crash(self):
        profile = self._make_profile(["warfarin"], [])
        profile.pop("supplements", None)
        # Should not raise
        alerts = check_interactions(profile)
        supp = [a for a in alerts if a.get("type") == "supplement-drug"]
        self.assertEqual(supp, [])


# ---------------------------------------------------------------------------
# Non-dipping BP nudge tests
# ---------------------------------------------------------------------------

class NonDippingBPNudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _write_vitals(self, entries):
        with ensure_metrics_db(self.root, "p1") as conn:
            for e in entries:
                conn.execute(
                    """INSERT INTO vital_entries
                       (entry_date, metric, value_text, unit, note, recorded_at,
                        numeric_value, systolic, diastolic)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (e["date"], e["metric"],
                     f"{e['systolic']}/{e['diastolic']}", "mmHg", "",
                     e["recorded_at"], None, e["systolic"], e["diastolic"]),
                )
            conn.commit()

    def _make_bp(self, hour, systolic):
        ts = f"2025-06-01T{hour:02d}:00:00Z"
        return {"metric": "blood_pressure", "systolic": systolic, "diastolic": 80,
                "recorded_at": ts, "date": "2025-06-01"}

    def test_non_dipping_detected(self):
        # Day avg = 150, night avg = 145 → dip = 3.3% < 10%
        entries = (
            [self._make_bp(h, 150) for h in range(8, 21)] +
            [self._make_bp(h, 145) for h in [22, 23, 0, 1]]
        )
        self._write_vitals(entries)
        profile = load_profile(self.root, "p1")
        profile["daily_checkins"] = []
        nudges = compute_nudges(self.root, "p1")
        titles = [n["title"] for n in nudges]
        non_dip = [t for t in titles if "dipping" in t.lower() or "non-dip" in t.lower()]
        self.assertTrue(len(non_dip) >= 1, f"Expected non-dipping nudge, got: {titles}")

    def test_normal_dipping_no_alert(self):
        # Day avg = 150, night avg = 128 → dip = 14.7% ≥ 10%
        entries = (
            [self._make_bp(h, 150) for h in range(8, 21)] +
            [self._make_bp(h, 128) for h in [22, 23, 0, 1]]
        )
        self._write_vitals(entries)
        nudges = compute_nudges(self.root, "p1")
        titles = [n["title"] for n in nudges]
        non_dip = [t for t in titles if "non-dip" in t.lower() or "dipping" in t.lower()]
        self.assertEqual(non_dip, [])

    def test_insufficient_bp_readings_no_crash(self):
        # Only 2 night readings — should not produce nudge (requires ≥3)
        entries = (
            [self._make_bp(h, 150) for h in range(8, 21)] +
            [self._make_bp(h, 145) for h in [22, 23]]
        )
        self._write_vitals(entries)
        nudges = compute_nudges(self.root, "p1")  # must not raise
        self.assertIsInstance(nudges, list)


# ---------------------------------------------------------------------------
# Run metrics / run_summary tests
# ---------------------------------------------------------------------------

class RunSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _add_run(self, profile, date_s, distance_km, pace_min_km, hr=None, tss=None, vo2=None):
        w = {
            "type": "run",
            "date": date_s,
            "distance_km": distance_km,
            "pace_min_km": pace_min_km,
        }
        if hr is not None:
            w["hr_avg"] = hr
        if tss is not None:
            w["tss"] = tss
        if vo2 is not None:
            w["vo2max_est"] = vo2
        profile.setdefault("workouts", []).append(w)

    def test_run_summary_basic(self):
        profile = load_profile(self.root, "p1")
        self._add_run(profile, "2025-01-01", 5.0, 5.5, hr=145)
        self._add_run(profile, "2025-01-03", 7.0, 5.2, hr=148)
        self._add_run(profile, "2025-01-05", 8.0, 5.0, hr=150)
        save_profile(self.root, "p1", profile)
        runs = run_summary(self.root, "p1", n=5)
        self.assertEqual(len(runs), 3)
        # Most recent last
        self.assertEqual(runs[-1]["date"], "2025-01-05")

    def test_run_summary_deltas(self):
        profile = load_profile(self.root, "p1")
        self._add_run(profile, "2025-01-01", 5.0, 5.5, hr=150, tss=60, vo2=45.0)
        self._add_run(profile, "2025-01-03", 5.0, 5.2, hr=148, tss=58, vo2=45.5)
        save_profile(self.root, "p1", profile)
        runs = run_summary(self.root, "p1", n=5)
        second = runs[1]
        # pace improved (lower) → delta should be negative seconds
        self.assertIn("pace_delta_s", second)
        self.assertLess(second["pace_delta_s"], 0)

    def test_run_summary_no_runs(self):
        runs = run_summary(self.root, "p1", n=5)
        self.assertEqual(runs, [])

    def test_run_summary_respects_n(self):
        profile = load_profile(self.root, "p1")
        for i in range(10):
            self._add_run(profile, f"2025-01-{i+1:02d}", 5.0, 5.5)
        save_profile(self.root, "p1", profile)
        runs = run_summary(self.root, "p1", n=3)
        self.assertEqual(len(runs), 3)

    def test_non_run_workouts_excluded(self):
        profile = load_profile(self.root, "p1")
        self._add_run(profile, "2025-01-01", 5.0, 5.5)
        profile["workouts"].append({"type": "cycling", "date": "2025-01-02", "distance_km": 20})
        save_profile(self.root, "p1", profile)
        runs = run_summary(self.root, "p1", n=5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["date"], "2025-01-01")


# ---------------------------------------------------------------------------
# Intervention tracker tests
# ---------------------------------------------------------------------------

class InterventionTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_log_intervention_creates_record(self):
        rec = log_intervention(
            self.root, "p1",
            name="time-restricted eating",
            start_date="2025-01-15",
            protocol="16:8 window, stop eating by 20:00",
            outcome_metric="weight_kg",
        )
        self.assertEqual(rec["name"], "time-restricted eating")
        self.assertEqual(rec["start_date"], "2025-01-15")
        self.assertEqual(rec["status"], "active")

    def test_log_intervention_persisted(self):
        log_intervention(
            self.root, "p1",
            name="cold exposure",
            start_date="2025-02-01",
            protocol="2-min cold shower daily",
            outcome_metric="rhr",
        )
        profile = load_profile(self.root, "p1")
        ivs = profile.get("interventions", [])
        names = [iv["name"] for iv in ivs]
        self.assertIn("cold exposure", names)

    def test_log_intervention_upsert(self):
        log_intervention(self.root, "p1", name="IF", start_date="2025-01-01",
                         protocol="v1", outcome_metric="weight_kg")
        log_intervention(self.root, "p1", name="IF", start_date="2025-01-15",
                         protocol="v2 updated", outcome_metric="weight_kg")
        profile = load_profile(self.root, "p1")
        ivs = profile.get("interventions", [])
        # Should only have one entry named "IF"
        matching = [iv for iv in ivs if iv["name"].upper() == "IF"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["protocol"], "v2 updated")

    def test_intervention_status_days_running(self):
        today = date.today()
        start = (today - timedelta(days=14)).isoformat()
        log_intervention(self.root, "p1", name="zone2", start_date=start,
                         protocol="3x 45min per week", outcome_metric="rhr")
        items = intervention_status(self.root, "p1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["days_running"], 14)

    def test_intervention_status_empty(self):
        items = intervention_status(self.root, "p1")
        self.assertEqual(items, [])

    def test_log_multiple_interventions(self):
        log_intervention(self.root, "p1", name="IF", start_date="2025-01-01",
                         protocol="16:8", outcome_metric="weight_kg")
        log_intervention(self.root, "p1", name="zone2", start_date="2025-02-01",
                         protocol="3x weekly", outcome_metric="rhr")
        items = intervention_status(self.root, "p1")
        self.assertEqual(len(items), 2)


# ---------------------------------------------------------------------------
# CLI wiring tests
# ---------------------------------------------------------------------------

class CLIWiringV221Tests(unittest.TestCase):
    def test_v221_subcommands_present(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        for cmd in ["run-summary", "log-intervention", "intervention-status"]:
            self.assertIn(cmd, choices, f"missing CLI command: {cmd}")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Greeting / hi command tests
# ---------------------------------------------------------------------------

class GreetingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1", name="Anna")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _save(self, profile):
        save_profile(self.root, "p1", profile)

    def test_fresh_workspace_default_opener(self):
        from scripts.greeting import build_greeting
        g = build_greeting(self.root, "p1")
        self.assertIn("Anna", g)
        self.assertTrue(g.endswith("?"))

    def test_high_pain_takes_priority(self):
        from scripts.greeting import build_greeting
        from datetime import timedelta
        p = load_profile(self.root, "p1")
        p["daily_checkins"] = [
            {"date": str(date.today() - timedelta(days=i)), "pain": 8.0,
             "mood": 6, "sleep_hours": 7, "energy": 5}
            for i in range(5)
        ]
        self._save(p)
        g = build_greeting(self.root, "p1")
        self.assertIn("pain", g.lower())

    def test_stale_checkin_mentions_gap(self):
        from scripts.greeting import build_greeting
        from datetime import timedelta
        p = load_profile(self.root, "p1")
        p["daily_checkins"] = [
            {"date": str(date.today() - timedelta(days=7)),
             "mood": 7, "sleep_hours": 6.0, "energy": 6, "pain": 1}
        ]
        self._save(p)
        g = build_greeting(self.root, "p1")
        self.assertIn("days", g.lower())

    def test_active_intervention_mentioned(self):
        from scripts.greeting import build_greeting
        from datetime import timedelta
        p = load_profile(self.root, "p1")
        p["interventions"] = [{
            "name": "zone2 training", "start_date": str(date.today() - timedelta(days=10)),
            "protocol": "3x/week", "outcome_metric": "rhr", "status": "active"
        }]
        self._save(p)
        g = build_greeting(self.root, "p1")
        self.assertIn("zone2", g.lower())

    def test_burnout_signal_detected(self):
        from scripts.greeting import build_greeting
        from datetime import timedelta
        p = load_profile(self.root, "p1")
        p["daily_checkins"] = [
            {"date": str(date.today() - timedelta(days=i)),
             "mood": 3.0, "energy": 2.5, "sleep_hours": 6, "pain": 1}
            for i in range(10)
        ]
        self._save(p)
        g = build_greeting(self.root, "p1")
        self.assertIn("?", g)
        self.assertTrue(
            any(w in g.lower() for w in ["mood", "energy", "going on", "lower"]),
            f"Expected burnout language, got: {g}"
        )

    def test_hi_hello_hey_commands_wired(self):
        from scripts.commands import build_parser
        choices = build_parser()._subparsers._group_actions[0].choices
        for cmd in ("hi", "hello", "hey"):
            self.assertIn(cmd, choices, f"missing command: {cmd}")

    def test_greeting_ends_with_question(self):
        from scripts.greeting import build_greeting
        g = build_greeting(self.root, "p1")
        self.assertTrue(g.strip().endswith("?"), f"Greeting should end with question: {g}")
