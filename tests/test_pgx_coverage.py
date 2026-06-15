"""Coverage-awareness tests for pharmacogenomics: missing / no-call genotype data
must NOT be reported as a confident 'normal / standard dosing' result.

These encode the clinical-safety contract: absence of a result is not a clear result.
"""

import os
import tempfile
import unittest
from pathlib import Path

from scripts.pharmacogenomics import (
    call_all_phenotypes,
    parse_raw_genotype_file,
    pgx_drug_alerts,
    render_pgx_report as build_pgx_report,
)

ALL_GENES = ("CYP2C19", "CYP2D6", "CYP2C9", "SLCO1B1", "VKORC1", "MTHFR", "DPYD")


class PGXCoverageTests(unittest.TestCase):
    def test_empty_genotype_is_indeterminate_not_normal(self):
        ph = call_all_phenotypes({})
        for gene in ALL_GENES:
            self.assertEqual(
                ph[gene]["phenotype"], "indeterminate",
                f"{gene} must be indeterminate (not normal) when no genotype data is present",
            )

    def test_no_call_dashes_are_indeterminate(self):
        ph = call_all_phenotypes({"rs3918290": "--", "rs55886062": "--"})
        self.assertEqual(ph["DPYD"]["phenotype"], "indeterminate")

    def test_dpyd_homozygous_is_poor(self):
        ph = call_all_phenotypes({"rs3918290": "AA"})
        self.assertEqual(ph["DPYD"]["phenotype"], "poor_metaboliser")

    def test_dpyd_heterozygous_is_intermediate_not_poor(self):
        # A single *2A allele is partial DPD deficiency (intermediate), not full PM.
        ph = call_all_phenotypes({"rs3918290": "GA"})
        self.assertEqual(ph["DPYD"]["phenotype"], "intermediate_metaboliser")

    def test_covered_non_risk_gene_is_still_normal(self):
        # Real genotypes present, none are risk alleles -> covered and normal (regression guard).
        ph = call_all_phenotypes({"rs4244285": "GG", "rs4986893": "GG", "rs12248560": "CC"})
        self.assertEqual(ph["CYP2C19"]["phenotype"], "normal_metaboliser")

    def test_indeterminate_dpyd_on_capecitabine_raises_critical_coverage_alert(self):
        ph = call_all_phenotypes({})  # DPYD indeterminate
        alerts = pgx_drug_alerts(ph, [{"name": "capecitabine"}])
        self.assertTrue(
            any(a["gene"] == "DPYD" and a["severity"] == "critical" for a in alerts),
            "indeterminate DPYD + capecitabine must raise a critical coverage alert, not stay silent",
        )

    def test_no_coverage_alert_when_gene_assessed_normal(self):
        # All assessed-normal + clopidogrel -> still no alerts (regression guard).
        ph = call_all_phenotypes({
            "rs4244285": "GG", "rs4986893": "GG", "rs12248560": "CC",
        })
        # Only CYP2C19 is covered here; the rest are indeterminate but patient is on
        # clopidogrel (a CYP2C19 drug), and CYP2C19 is assessed normal -> no alert for it.
        alerts = pgx_drug_alerts(ph, [{"name": "clopidogrel"}])
        self.assertFalse(
            any(a["gene"] == "CYP2C19" for a in alerts),
            "assessed-normal CYP2C19 must not raise an alert for clopidogrel",
        )

    def test_report_does_not_clear_unassessed_dpyd(self):
        ph = call_all_phenotypes({})
        text = build_pgx_report(ph, [], variants_found=0)
        self.assertNotIn("Standard fluorouracil/capecitabine dosing applies", text)
        self.assertIn("not assessed", text.lower())

    # --- per-allele (partial) coverage: a benign companion call must NOT clear an
    #     untested risk allele (the silent-fatal-clearance hole) ---

    def test_partial_coverage_with_risk_snp_nocall_is_indeterminate(self):
        # DPYD *2A (the fatal LoF allele) is a no-call; *13 is a benign real call.
        ph = call_all_phenotypes({"rs3918290": "--", "rs55886062": "GG"})
        self.assertEqual(ph["DPYD"]["phenotype"], "indeterminate")

    def test_partial_coverage_dpyd_capecitabine_still_alerts(self):
        ph = call_all_phenotypes({"rs3918290": "--", "rs55886062": "GG"})
        alerts = pgx_drug_alerts(ph, [{"name": "capecitabine"}])
        self.assertTrue(any(a["gene"] == "DPYD" and a["severity"] == "critical" for a in alerts))

    def test_partial_cyp2d6_missing_lof_is_indeterminate(self):
        # Only *10 probed; the European PM-defining *4/*6 alleles are untested.
        ph = call_all_phenotypes({"rs1065852": "CC"})
        self.assertEqual(ph["CYP2D6"]["phenotype"], "indeterminate")

    def test_observed_risk_under_partial_coverage_is_kept_not_hidden(self):
        # A risk allele actually seen must still be reported (not downgraded to indeterminate).
        ph = call_all_phenotypes({"rs3918290": "GA"})  # *13 untested, but *2A het observed
        self.assertEqual(ph["DPYD"]["phenotype"], "intermediate_metaboliser")

    # --- per-ALLELE no-calls: half-calls and non-standard sentinels must not clear a gene ---

    def test_half_call_token_is_not_coverage(self):
        ph = call_all_phenotypes({"rs3918290": "G-", "rs55886062": "GG"})
        self.assertEqual(ph["DPYD"]["phenotype"], "indeterminate")

    def test_single_base_token_is_not_coverage(self):
        ph = call_all_phenotypes({"rs3918290": "G"})
        self.assertEqual(ph["DPYD"]["phenotype"], "indeterminate")

    def _write(self, content: str) -> Path:
        fd, name = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        path = Path(name)
        self.addCleanup(path.unlink)
        return path

    def test_parser_halfcall_becomes_nocall(self):
        p = self._write("rs3918290\t1\t97915614\tG-\nrs55886062\t1\t97915615\tGG\n")
        v = parse_raw_genotype_file(p)
        self.assertEqual(v.get("rs3918290"), "--")

    def test_parser_ancestrydna_homozygous_combines_alleles(self):
        # AncestryDNA 5-column layout: the two alleles live in separate columns.
        p = self._write("rs3918290\t1\t97915614\tA\tA\n")
        v = parse_raw_genotype_file(p)
        self.assertEqual(v.get("rs3918290"), "AA")
        self.assertEqual(call_all_phenotypes(v)["DPYD"]["phenotype"], "poor_metaboliser")

    def test_parser_ancestrydna_nocall_zero_is_indeterminate(self):
        p = self._write("rs3918290\t1\t97915614\t0\t0\nrs55886062\t1\t97915615\tG\tG\n")
        v = parse_raw_genotype_file(p)
        self.assertEqual(v.get("rs3918290"), "--")
        self.assertEqual(call_all_phenotypes(v)["DPYD"]["phenotype"], "indeterminate")


if __name__ == "__main__":
    unittest.main()
