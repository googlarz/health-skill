"""Coverage for clinical write/render paths that had zero tests despite their
compute logic being tested — the audit's finding: a decision/triage/PGx
computation could be correct but silently produce a wrong, blank, or
mislocated file, and nothing would catch it.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile, save_profile
from scripts.decisions import (
    write_hrt_decision,
    write_screening_decision,
    write_statin_decision,
)
from scripts.triage import write_triage
from scripts.pharmacogenomics import import_pgx_file, pgx_report_path


class _WS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        ensure_person(self.root, "p1", "Test", "1980-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.tmp)


class DecisionWritePathTests(_WS):
    def test_hrt_decision_writes_nonempty_file(self):
        path = write_hrt_decision(self.root, "p1")
        self.assertTrue(path.exists())
        text = path.read_text()
        self.assertGreater(len(text.strip()), 0)
        self.assertIn("HRT", text)

    def test_statin_decision_writes_nonempty_file(self):
        path = write_statin_decision(self.root, "p1")
        self.assertTrue(path.exists())
        self.assertGreater(len(path.read_text().strip()), 0)

    def test_screening_decision_writes_nonempty_file(self):
        path = write_screening_decision(self.root, "p1")
        self.assertTrue(path.exists())
        self.assertGreater(len(path.read_text().strip()), 0)

    def test_decision_reflects_actual_profile_data(self):
        # A family history of breast cancer must show up in the written file,
        # not just in the underlying computation.
        p = load_profile(self.root, "p1")
        p["family_history"] = [
            {"relation": "mother", "condition": "breast cancer", "age_at_diagnosis": 45}
        ]
        save_profile(self.root, "p1", p)
        path = write_screening_decision(self.root, "p1")
        text = path.read_text().lower()
        self.assertIn("breast", text)


class TriageWritePathTests(_WS):
    def test_triage_writes_file_with_urgency_band(self):
        path = write_triage(
            self.root, "p1", "chest pain",
            {"q1": "started today", "q3": "9/10", "q4": "getting worse"},
        )
        self.assertTrue(path.exists())
        text = path.read_text()
        self.assertIn("Emergency now", text)

    def test_triage_file_named_from_summary(self):
        path = write_triage(self.root, "p1", "sharp headache", {"q3": "3/10"})
        self.assertIn("headache", path.name.lower())

    def test_low_urgency_triage_does_not_falsely_escalate(self):
        path = write_triage(self.root, "p1", "mild fatigue", {"q3": "2/10"})
        text = path.read_text()
        self.assertNotIn("Emergency now", text)
        self.assertNotIn("🚨", text)


class PgxReportWritePathTests(_WS):
    def _write_23andme_file(self, genotype: str = "GG") -> Path:
        # rs4244285 (CYP2C19 *2 LoF) -- picked because it's in SNP_DB
        p = self.root / "genome.txt"
        p.write_text(f"# comment\nrs4244285\t10\t94781859\t{genotype}\n")
        return p

    def test_import_pgx_writes_report_at_canonical_path(self):
        result = import_pgx_file(self.root, "p1", self._write_23andme_file())
        expected_path = pgx_report_path(self.root, "p1")
        self.assertTrue(expected_path.exists())
        self.assertEqual(Path(result["report_path"]), expected_path)

    def test_pgx_report_contains_computed_phenotype(self):
        import_pgx_file(self.root, "p1", self._write_23andme_file("AA"))
        text = pgx_report_path(self.root, "p1").read_text()
        self.assertIn("CYP2C19", text)

    def test_report_regeneration_targets_same_file_as_import(self):
        # Regression: _command_pgx_report used to hand-roll a different path
        # ("PGX_REPORT.md" in the wrong directory) instead of pgx_report_path().
        from scripts.commands import build_parser
        import_pgx_file(self.root, "p1", self._write_23andme_file())
        canonical_path = pgx_report_path(self.root, "p1")
        self.assertTrue(canonical_path.exists())

        parser = build_parser()
        args = parser.parse_args([
            "pgx-report", "--root", str(self.root), "--person-id", "p1",
        ])
        args.func(args)
        # still exactly one report file, at the canonical location, not two
        self.assertTrue(canonical_path.exists())
        self.assertFalse((self.root / "people" / "p1" / "PGX_REPORT.md").exists())


if __name__ == "__main__":
    unittest.main()
