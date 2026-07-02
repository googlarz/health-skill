"""Red-team guard for the pharmacogenomics safety invariant.

The load-bearing guarantee of this module: incomplete, malformed, or absent
genotype data must NEVER produce a confident clearance ("normal / standard
dosing"). This file brute-forces every gene against every non-real token
permutation and asserts that invariant holds at all three layers — phenotype
caller, drug-alert layer, and raw-file parser.

If any assertion here fails, a patient could be told a drug is safe on data
that never tested the risk allele. Treat a failure as release-blocking.
"""

import tempfile
import unittest
from pathlib import Path

from scripts.pharmacogenomics import (
    DRUG_IMPLICATIONS,
    GENE_RSIDS,
    _BASELINE_PHENOTYPES,
    _is_real_call,
    call_all_phenotypes,
    parse_raw_genotype_file,
    pgx_drug_alerts,
)

# Every way real-world files express "no usable call for this allele".
NON_REAL_TOKENS = [
    "--", "- -", "", " ", "0", "00", "0 0", "NN", "N", "N N",
    "G", "A", "C", "T",            # single base (half of a diploid call)
    "G-", "-G", "A-", "-A", "N-",  # half-calls
    "II", "DD", "ID", "I", "D",    # indel tokens (not A/C/G/T)
    "?", "??", "..",
]

GENES = list(GENE_RSIDS.keys())


class TokenSanityTests(unittest.TestCase):
    def test_none_of_the_redteam_tokens_are_real_calls(self):
        # If any "bad" token were accepted as real, the whole premise below is void.
        for tok in NON_REAL_TOKENS:
            self.assertFalse(_is_real_call(tok), f"{tok!r} must not count as a real call")

    def test_real_calls_are_accepted(self):
        for tok in ("AA", "AG", "CT", "gg", "aC"):
            self.assertTrue(_is_real_call(tok), f"{tok!r} should be a real call")


class PhenotypeNeverClearsOnBadData(unittest.TestCase):
    def test_all_bad_tokens_yield_indeterminate_for_every_gene(self):
        for gene in GENES:
            rsids = GENE_RSIDS[gene]
            for tok in NON_REAL_TOKENS:
                variants = {r: tok for r in rsids}
                pheno = call_all_phenotypes(variants)[gene]["phenotype"]
                self.assertNotIn(
                    pheno, _BASELINE_PHENOTYPES,
                    f"{gene} cleared to {pheno!r} on all-{tok!r} data",
                )
                self.assertEqual(
                    pheno, "indeterminate",
                    f"{gene} on all-{tok!r} should be indeterminate, got {pheno!r}",
                )

    def test_one_benign_call_cannot_clear_a_gene_with_untested_alleles(self):
        # A single real reference call plus any no-call on the remaining decision
        # SNPs must NOT let the gene resolve to a clearance (per-allele coverage).
        for gene in GENES:
            rsids = GENE_RSIDS[gene]
            if len(rsids) < 2:
                continue  # can't be "partial" with only one decision SNP
            variants = {rsids[0]: "AA"}
            for r in rsids[1:]:
                variants[r] = "--"
            pheno = call_all_phenotypes(variants)[gene]["phenotype"]
            self.assertNotIn(
                pheno, _BASELINE_PHENOTYPES,
                f"{gene} cleared on partial coverage (1 real + {len(rsids)-1} no-call)",
            )


class DrugAlertsNeverSilentOnBadData(unittest.TestCase):
    def test_indeterminate_gene_on_governed_med_always_alerts(self):
        # For every drug rule: if the governing gene is indeterminate and the
        # patient is on a governed med, an alert MUST surface — never silence.
        for rule in DRUG_IMPLICATIONS:
            gene = rule["gene"]
            med = rule["medications"][0]
            phenotypes = {gene: {"phenotype": "indeterminate", "label": "Not assessed"}}
            alerts = pgx_drug_alerts(phenotypes, [{"name": med}])
            self.assertTrue(
                any(a["gene"] == gene for a in alerts),
                f"no alert for indeterminate {gene} while on {med!r}",
            )

    def test_end_to_end_bad_data_plus_governed_med_alerts(self):
        # Full pipeline: garbage genotype + a governed med → phenotype is
        # indeterminate AND the drug layer flags it.
        for rule in DRUG_IMPLICATIONS:
            gene = rule["gene"]
            med = rule["medications"][0]
            variants = {r: "--" for r in GENE_RSIDS[gene]}
            phenotypes = call_all_phenotypes(variants)
            self.assertEqual(phenotypes[gene]["phenotype"], "indeterminate")
            alerts = pgx_drug_alerts(phenotypes, [{"name": med}])
            self.assertTrue(
                any(a["gene"] == gene for a in alerts),
                f"pipeline stayed silent: all-no-call {gene} on {med!r}",
            )


class ParserNeverFabricatesACall(unittest.TestCase):
    def _write(self, content: str) -> Path:
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        fh.write(content)
        fh.close()
        return Path(fh.name)

    def test_bad_tokens_parse_to_nocall_not_a_real_call(self):
        rsid = next(iter(GENE_RSIDS[GENES[0]]))  # any known rsid
        for tok in NON_REAL_TOKENS:
            # 23andMe tab format: rsid, chrom, pos, genotype
            path = self._write(f"# header\n{rsid}\t1\t12345\t{tok}\n")
            try:
                variants = parse_raw_genotype_file(path)
            finally:
                path.unlink()
            got = variants.get(rsid)
            if got is not None:
                self.assertFalse(
                    _is_real_call(got),
                    f"parser turned {tok!r} into real call {got!r}",
                )

    def test_ancestrydna_split_nocall_alleles_are_not_fabricated(self):
        rsid = next(iter(GENE_RSIDS[GENES[0]]))
        # AncestryDNA 5-col: rsid, chrom, pos, allele1, allele2 — both no-call.
        for a1, a2 in [("0", "0"), ("-", "-"), ("G", "0"), ("0", "G")]:
            path = self._write(f"{rsid}\t1\t12345\t{a1}\t{a2}\n")
            try:
                variants = parse_raw_genotype_file(path)
            finally:
                path.unlink()
            got = variants.get(rsid)
            if got is not None:
                self.assertFalse(
                    _is_real_call(got),
                    f"parser fabricated {got!r} from alleles {a1!r},{a2!r}",
                )


if __name__ == "__main__":
    unittest.main()
