#!/usr/bin/env python3
"""Pharmacogenomics (PGx) — 23andMe / AncestryDNA raw file parser.

Parses a raw genotype file, calls metabolizer phenotypes for key drug-metabolising
genes, and generates medication implications based on the person's current drug list.

Supported genes and their clinical relevance:
  CYP2C19  — clopidogrel, PPIs, many SSRIs/SNRIs, voriconazole
  CYP2D6   — codeine/tramadol (safety), tamoxifen (efficacy), many antidepressants
  CYP2C9   — warfarin (dose), NSAIDs, some sulfonylureas
  SLCO1B1  — statin myopathy risk
  VKORC1   — warfarin sensitivity (dose requirement)
  MTHFR    — folate metabolism, homocysteine, B12/folate interpretation
  HLA-B    — abacavir hypersensitivity (HLA-B*5701)
  DPYD     — fluorouracil/capecitabine toxicity

Usage:
    from pharmacogenomics import import_pgx_file
    counts = import_pgx_file(root, person_id, Path("inbox/genome_full_v5_Full.txt"))
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_profile,
        person_dir,
        save_profile,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_profile,
        person_dir,
        save_profile,
        workspace_lock,
    )

PGX_REPORT_FILENAME = "PHARMACOGENOMICS.md"


def pgx_report_path(root: Path, person_id: str) -> Path:
    return person_dir(root, person_id) / PGX_REPORT_FILENAME


# ---------------------------------------------------------------------------
# SNP database
# rsID → {allele → effect, gene, notes}
# ---------------------------------------------------------------------------

SNP_DB: dict[str, dict[str, Any]] = {
    # ── CYP2C19 ─────────────────────────────────────────────────────────────
    # *2 allele (loss of function) — most common LoF variant
    "rs4244285": {
        "gene": "CYP2C19", "star_allele": "*2",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "CYP2C19*2 — reduced enzyme activity. Common in all populations.",
    },
    # *3 allele (loss of function) — more common in Asian populations
    "rs4986893": {
        "gene": "CYP2C19", "star_allele": "*3",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "CYP2C19*3 — loss of function. More common in East Asian populations.",
    },
    # *17 allele (gain of function — ultrarapid metaboliser)
    "rs12248560": {
        "gene": "CYP2C19", "star_allele": "*17",
        "risk_allele": "T",
        "effect": "gain_of_function",
        "note": "CYP2C19*17 — increased enzyme activity (ultrarapid metaboliser).",
    },

    # ── CYP2D6 ──────────────────────────────────────────────────────────────
    # *4 allele (most common poor metaboliser variant in Europeans)
    "rs3892097": {
        "gene": "CYP2D6", "star_allele": "*4",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "CYP2D6*4 — non-functional allele. ~20% of Europeans carry one copy.",
    },
    # *6 allele (frameshift, loss of function)
    "rs5030655": {
        "gene": "CYP2D6", "star_allele": "*6",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "CYP2D6*6 — frameshift mutation, no enzyme activity.",
    },
    # *10 allele (reduced function, common in East Asians)
    "rs1065852": {
        "gene": "CYP2D6", "star_allele": "*10",
        "risk_allele": "T",
        "effect": "reduced_function",
        "note": "CYP2D6*10 — reduced activity. Common in East Asian populations.",
    },

    # ── CYP2C9 ──────────────────────────────────────────────────────────────
    # *2 allele
    "rs1799853": {
        "gene": "CYP2C9", "star_allele": "*2",
        "risk_allele": "T",
        "effect": "reduced_function",
        "note": "CYP2C9*2 — ~30% reduced enzyme activity.",
    },
    # *3 allele (more severe reduction)
    "rs1057910": {
        "gene": "CYP2C9", "star_allele": "*3",
        "risk_allele": "C",
        "effect": "reduced_function",
        "note": "CYP2C9*3 — ~90% reduced enzyme activity. Significant warfarin dose reduction needed.",
    },

    # ── SLCO1B1 (statin transport) ────────────────────────────────────────────
    "rs4149056": {
        "gene": "SLCO1B1", "star_allele": "*5",
        "risk_allele": "C",
        "effect": "reduced_transport",
        "note": "SLCO1B1*5 — reduced hepatic uptake of statins → higher plasma levels → myopathy risk.",
    },

    # ── VKORC1 (warfarin target) ─────────────────────────────────────────────
    "rs9923231": {
        "gene": "VKORC1", "star_allele": "-1639G>A",
        "risk_allele": "T",  # A allele in forward strand = T on reverse
        "effect": "reduced_sensitivity",
        "note": "VKORC1 -1639A allele — reduced VKORC1 expression. Low warfarin dose needed.",
    },

    # ── MTHFR ───────────────────────────────────────────────────────────────
    "rs1801133": {
        "gene": "MTHFR", "star_allele": "C677T",
        "risk_allele": "A",  # T allele (forward) = A on 23andMe orientation
        "effect": "reduced_function",
        "note": "MTHFR C677T — reduced folate metabolism. Homozygous (TT) associated with elevated homocysteine.",
    },
    "rs1801131": {
        "gene": "MTHFR", "star_allele": "A1298C",
        "risk_allele": "G",  # C allele
        "effect": "reduced_function",
        "note": "MTHFR A1298C — additional folate cycle impact when combined with C677T.",
    },

    # ── DPYD (fluorouracil toxicity) ─────────────────────────────────────────
    "rs3918290": {
        "gene": "DPYD", "star_allele": "*2A",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "DPYD*2A — severely reduced DPD enzyme. Fluorouracil/capecitabine can be fatal at standard doses.",
    },
    "rs55886062": {
        "gene": "DPYD", "star_allele": "*13",
        "risk_allele": "A",
        "effect": "loss_of_function",
        "note": "DPYD*13 — loss of function. Reduced fluorouracil tolerance.",
    },
}

# ---------------------------------------------------------------------------
# Gene phenotype callers
# Input: list of (rsid, genotype) for all variants in a gene
# Output: phenotype string
# ---------------------------------------------------------------------------

def _count_risk_alleles(gene_variants: list[tuple[str, str]]) -> int:
    """Count total risk alleles across all variants for a gene."""
    count = 0
    for rsid, genotype in gene_variants:
        if rsid not in SNP_DB:
            continue
        risk = SNP_DB[rsid]["risk_allele"]
        count += genotype.count(risk)
    return count


def _call_cyp2c19(variants: dict[str, str]) -> dict[str, str]:
    """Call CYP2C19 metaboliser status."""
    lof_rsids = ["rs4244285", "rs4986893"]  # *2, *3
    gof_rsids = ["rs12248560"]              # *17

    lof_count = sum(variants.get(r, "--").count(SNP_DB[r]["risk_allele"])
                    for r in lof_rsids if r in SNP_DB)
    gof_count = sum(variants.get(r, "--").count(SNP_DB[r]["risk_allele"])
                    for r in gof_rsids if r in SNP_DB)

    if lof_count >= 2:
        phenotype = "poor_metaboliser"
        label = "Poor metaboliser (PM)"
        implication = "Significantly reduced CYP2C19 activity."
    elif lof_count == 1 and gof_count == 0:
        phenotype = "intermediate_metaboliser"
        label = "Intermediate metaboliser (IM)"
        implication = "Moderately reduced CYP2C19 activity."
    elif lof_count == 0 and gof_count >= 2:
        phenotype = "ultrarapid_metaboliser"
        label = "Ultrarapid metaboliser (UM)"
        implication = "Increased CYP2C19 activity — may metabolise drugs faster."
    elif lof_count == 0 and gof_count == 1:
        phenotype = "rapid_metaboliser"
        label = "Rapid metaboliser (RM)"
        implication = "Slightly increased CYP2C19 activity."
    else:
        phenotype = "normal_metaboliser"
        label = "Normal metaboliser (NM)"
        implication = "Normal CYP2C19 activity."

    return {"phenotype": phenotype, "label": label, "implication": implication}


def _call_cyp2d6(variants: dict[str, str]) -> dict[str, str]:
    lof_rsids = ["rs3892097", "rs5030655"]
    reduced_rsids = ["rs1065852"]

    lof = sum(variants.get(r, "--").count(SNP_DB[r]["risk_allele"])
              for r in lof_rsids if r in SNP_DB)
    reduced = sum(variants.get(r, "--").count(SNP_DB[r]["risk_allele"])
                  for r in reduced_rsids if r in SNP_DB)

    if lof >= 2:
        return {"phenotype": "poor_metaboliser", "label": "Poor metaboliser (PM)",
                "implication": "Cannot convert codeine/tramadol to active form. Reduced tamoxifen activation."}
    if lof == 1:
        return {"phenotype": "intermediate_metaboliser", "label": "Intermediate metaboliser (IM)",
                "implication": "Reduced CYP2D6 activity. Caution with codeine and tamoxifen."}
    if reduced >= 2:
        return {"phenotype": "intermediate_metaboliser", "label": "Intermediate metaboliser (IM)",
                "implication": "Reduced CYP2D6 activity (CYP2D6*10). Common in East Asian populations."}
    return {"phenotype": "normal_metaboliser", "label": "Normal metaboliser (NM)",
            "implication": "Normal CYP2D6 activity."}


def _call_cyp2c9(variants: dict[str, str]) -> dict[str, str]:
    s2 = variants.get("rs1799853", "--").count("T")
    s3 = variants.get("rs1057910", "--").count("C")
    total = s2 + s3 * 2  # *3 is more severe

    if s3 >= 2:
        return {"phenotype": "poor_metaboliser", "label": "Poor metaboliser (PM)",
                "implication": "~90% reduced warfarin/NSAID metabolism. Significant dose reduction needed."}
    if total >= 2:
        return {"phenotype": "intermediate_metaboliser", "label": "Intermediate metaboliser (IM)",
                "implication": "Reduced CYP2C9 activity. Lower warfarin starting dose recommended."}
    if total == 1:
        return {"phenotype": "intermediate_metaboliser", "label": "Intermediate metaboliser (IM)",
                "implication": "Moderately reduced CYP2C9 — affects warfarin dosing."}
    return {"phenotype": "normal_metaboliser", "label": "Normal metaboliser (NM)",
            "implication": "Normal CYP2C9 activity."}


def _call_slco1b1(variants: dict[str, str]) -> dict[str, str]:
    risk = variants.get("rs4149056", "--").count("C")
    if risk >= 2:
        return {"phenotype": "poor_function", "label": "Decreased function (homozygous)",
                "implication": "High statin myopathy risk. Prefer pravastatin or rosuvastatin at low doses."}
    if risk == 1:
        return {"phenotype": "intermediate_function", "label": "Decreased function (heterozygous)",
                "implication": "Moderate statin myopathy risk. Avoid high-dose simvastatin/lovastatin."}
    return {"phenotype": "normal_function", "label": "Normal function",
            "implication": "Normal statin transport."}


def _call_vkorc1(variants: dict[str, str]) -> dict[str, str]:
    # T allele = A allele in standard orientation = low expression = low warfarin dose
    risk = variants.get("rs9923231", "--").count("T")
    if risk >= 2:
        return {"phenotype": "low_dose_required", "label": "Low warfarin sensitivity (AA)",
                "implication": "Low warfarin dose typically required (~3 mg/day). High bleeding risk at standard doses."}
    if risk == 1:
        return {"phenotype": "moderate_dose", "label": "Intermediate warfarin sensitivity (GA)",
                "implication": "Moderate warfarin sensitivity. Below-average starting dose often appropriate."}
    return {"phenotype": "standard_dose", "label": "Standard warfarin sensitivity (GG)",
            "implication": "Standard warfarin dosing typically appropriate."}


def _call_mthfr(variants: dict[str, str]) -> dict[str, str]:
    c677t = variants.get("rs1801133", "--").count("A")  # T allele = A in 23andMe
    a1298c = variants.get("rs1801131", "--").count("G")

    if c677t >= 2:
        return {"phenotype": "homozygous_c677t", "label": "Homozygous C677T (TT)",
                "implication": "Significantly reduced MTHFR activity. Ensure adequate folate and B12. Check homocysteine."}
    if c677t == 1 and a1298c >= 1:
        return {"phenotype": "compound_heterozygous", "label": "Compound heterozygous (C677T + A1298C)",
                "implication": "Combined MTHFR variants. Similar impact to homozygous C677T. Monitor homocysteine."}
    if c677t == 1:
        return {"phenotype": "heterozygous_c677t", "label": "Heterozygous C677T (CT)",
                "implication": "Mildly reduced MTHFR activity. Standard folate intake usually sufficient."}
    return {"phenotype": "normal", "label": "No significant MTHFR variants",
            "implication": "Normal MTHFR activity."}


def _call_dpyd(variants: dict[str, str]) -> dict[str, str]:
    lof = (variants.get("rs3918290", "--").count("A") +
           variants.get("rs55886062", "--").count("A"))
    if lof >= 1:
        return {"phenotype": "poor_metaboliser", "label": "DPD deficiency detected",
                "implication": "CRITICAL: fluorouracil and capecitabine can cause severe or fatal toxicity. Do NOT use standard doses without DPYD testing and dose reduction."}
    return {"phenotype": "normal", "label": "No DPYD variants detected",
            "implication": "Normal DPD activity. Standard fluorouracil/capecitabine dosing applies."}


# ---------------------------------------------------------------------------
# Drug implications — given phenotypes, flag any current medications
# ---------------------------------------------------------------------------

DRUG_IMPLICATIONS: list[dict[str, Any]] = [
    # CYP2C19 — poor/intermediate
    {
        "gene": "CYP2C19",
        "phenotypes": ["poor_metaboliser", "intermediate_metaboliser"],
        "medications": ["clopidogrel", "plavix"],
        "severity": "critical",
        "message": (
            "Clopidogrel requires CYP2C19 to convert to its active form. "
            "Poor/intermediate metabolisers get inadequate antiplatelet effect — "
            "higher risk of heart attack or stroke if on clopidogrel for cardiac stenting. "
            "Alternative: ticagrelor or prasugrel (do not require CYP2C19 activation). "
            "Discuss urgently with your cardiologist."
        ),
    },
    {
        "gene": "CYP2C19",
        "phenotypes": ["poor_metaboliser"],
        "medications": ["omeprazole", "esomeprazole", "ppi"],
        "severity": "moderate",
        "message": (
            "PPIs are metabolised by CYP2C19. Poor metabolisers may have higher PPI levels "
            "than expected — usually not dangerous but worth knowing."
        ),
    },
    {
        "gene": "CYP2C19",
        "phenotypes": ["ultrarapid_metaboliser", "rapid_metaboliser"],
        "medications": ["sertraline", "escitalopram", "citalopram", "ssri", "venlafaxine", "duloxetine"],
        "severity": "moderate",
        "message": (
            "Ultrarapid CYP2C19 metabolisers may clear some SSRIs/SNRIs faster than average, "
            "potentially reducing their effectiveness. Discuss with your prescriber if you feel "
            "antidepressants are not working as expected."
        ),
    },
    # CYP2D6 — poor metaboliser
    {
        "gene": "CYP2D6",
        "phenotypes": ["poor_metaboliser"],
        "medications": ["codeine", "tramadol"],
        "severity": "critical",
        "message": (
            "CYP2D6 poor metabolisers cannot convert codeine or tramadol to their active forms. "
            "These drugs will not provide effective pain relief. "
            "Request an alternative opioid (hydromorphone, oxycodone, fentanyl) from your prescriber."
        ),
    },
    {
        "gene": "CYP2D6",
        "phenotypes": ["poor_metaboliser", "intermediate_metaboliser"],
        "medications": ["tamoxifen"],
        "severity": "major",
        "message": (
            "Tamoxifen requires CYP2D6 to convert to its active form (endoxifen). "
            "Poor/intermediate metabolisers have significantly reduced tamoxifen efficacy for breast cancer treatment. "
            "Discuss switching to an aromatase inhibitor (anastrozole, letrozole) with your oncologist."
        ),
    },
    {
        "gene": "CYP2D6",
        "phenotypes": ["poor_metaboliser"],
        "medications": ["fluoxetine", "paroxetine", "sertraline", "venlafaxine", "duloxetine"],
        "severity": "moderate",
        "message": (
            "CYP2D6 poor metabolisers may have higher-than-expected antidepressant levels. "
            "Side effects may be more pronounced at standard doses. Discuss with your prescriber."
        ),
    },
    # CYP2C9 — warfarin
    {
        "gene": "CYP2C9",
        "phenotypes": ["poor_metaboliser", "intermediate_metaboliser"],
        "medications": ["warfarin", "coumadin"],
        "severity": "major",
        "message": (
            "CYP2C9 variants reduce warfarin metabolism — standard doses cause higher blood levels. "
            "Requires significantly lower starting dose and closer INR monitoring. "
            "VKORC1 status (also in this report) refines the dose estimate further."
        ),
    },
    # SLCO1B1 — statins
    {
        "gene": "SLCO1B1",
        "phenotypes": ["poor_function", "intermediate_function"],
        "medications": ["statin", "simvastatin", "atorvastatin", "rosuvastatin", "lovastatin"],
        "severity": "major",
        "message": (
            "SLCO1B1 variant increases statin levels in the bloodstream. "
            "Elevated myopathy (muscle damage) risk, especially with simvastatin and lovastatin. "
            "Prefer pravastatin or rosuvastatin (less SLCO1B1-dependent). Avoid high-dose simvastatin."
        ),
    },
    # VKORC1 — warfarin
    {
        "gene": "VKORC1",
        "phenotypes": ["low_dose_required"],
        "medications": ["warfarin", "coumadin"],
        "severity": "major",
        "message": (
            "VKORC1 variant (AA genotype) means you need a much lower warfarin dose than average. "
            "Typical starting dose ~1.5–3 mg/day vs the standard 5 mg. "
            "Combined with CYP2C9 variants, bleeding risk at standard doses is very high."
        ),
    },
    # DPYD — chemotherapy
    {
        "gene": "DPYD",
        "phenotypes": ["poor_metaboliser"],
        "medications": ["fluorouracil", "capecitabine", "xeloda", "5-fu"],
        "severity": "critical",
        "message": (
            "CRITICAL: DPYD deficiency detected. Fluorouracil and capecitabine cannot be safely "
            "metabolised. Standard doses can cause life-threatening toxicity. "
            "Do NOT receive these drugs without urgent discussion with your oncologist."
        ),
    },
    # MTHFR — methotrexate, folate
    {
        "gene": "MTHFR",
        "phenotypes": ["homozygous_c677t", "compound_heterozygous"],
        "medications": ["methotrexate"],
        "severity": "moderate",
        "message": (
            "MTHFR variants may increase methotrexate side effects (mucositis, bone marrow effects). "
            "Ensure adequate folate supplementation as directed by your prescriber."
        ),
    },
]


def call_all_phenotypes(variants: dict[str, str]) -> dict[str, dict[str, str]]:
    """Call phenotypes for all supported genes given a dict of rsid→genotype."""
    return {
        "CYP2C19": _call_cyp2c19(variants),
        "CYP2D6":  _call_cyp2d6(variants),
        "CYP2C9":  _call_cyp2c9(variants),
        "SLCO1B1": _call_slco1b1(variants),
        "VKORC1":  _call_vkorc1(variants),
        "MTHFR":   _call_mthfr(variants),
        "DPYD":    _call_dpyd(variants),
    }


def pgx_drug_alerts(
    phenotypes: dict[str, dict[str, str]],
    medications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return medication-specific implications given phenotypes and current meds."""
    med_names = [(m.get("name") or "").lower() for m in medications]
    alerts: list[dict[str, Any]] = []

    for rule in DRUG_IMPLICATIONS:
        gene = rule["gene"]
        gene_phenotype = phenotypes.get(gene, {}).get("phenotype", "")
        if gene_phenotype not in rule["phenotypes"]:
            continue
        # Check if any of the flagged medications are in the current list
        matched_meds = [
            n for n in med_names
            if any(kw in n or n.startswith(kw) for kw in rule["medications"])
        ]
        if not matched_meds:
            continue
        alerts.append({
            "gene": gene,
            "phenotype": gene_phenotype,
            "medications": matched_meds,
            "severity": rule["severity"],
            "message": rule["message"],
        })

    order = {"critical": 0, "major": 1, "moderate": 2}
    alerts.sort(key=lambda a: order.get(a["severity"], 3))
    return alerts


# ---------------------------------------------------------------------------
# Raw file parser
# ---------------------------------------------------------------------------

def parse_raw_genotype_file(path: Path) -> dict[str, str]:
    """Parse a 23andMe or AncestryDNA raw genotype file.

    Returns dict: rsid → genotype string (e.g. "AG", "CC", "--")
    Only returns rsIDs that appear in SNP_DB.
    """
    target_rsids = set(SNP_DB.keys())
    variants: dict[str, str] = {}

    # Support gzip files (23andMe often distributes compressed)
    open_fn = gzip.open if path.suffix.lower() == ".gz" else open

    try:
        with open_fn(str(path), "rt", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 4:
                    # AncestryDNA uses comma-separated with different structure
                    parts = line.split(",")
                if len(parts) < 4:
                    continue
                rsid = parts[0].strip()
                if rsid not in target_rsids:
                    continue
                genotype = parts[3].strip().upper().replace("-", "")
                if genotype in ("", "00"):
                    genotype = "--"
                variants[rsid] = genotype
    except (OSError, EOFError):
        pass

    return variants


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def render_pgx_report(
    phenotypes: dict[str, dict[str, str]],
    alerts: list[dict[str, Any]],
    variants_found: int,
) -> str:
    from datetime import date
    today = date.today()
    lines = [
        "# Pharmacogenomics Report",
        "",
        f"_Generated {today.isoformat()} · {variants_found} relevant variants analysed_",
        "",
        "> Pharmacogenomics shows how your genes affect how your body processes medications.",
        "> This report is informational — discuss any implications with your prescriber before",
        "> making any changes to your medications.",
        "",
    ]

    # Gene summary table
    lines.append("## Gene summary\n")
    lines.append("| Gene | Phenotype | Clinical relevance |")
    lines.append("|------|-----------|-------------------|")

    gene_relevance = {
        "CYP2C19": "Clopidogrel, PPIs, many SSRIs",
        "CYP2D6":  "Codeine/tramadol, tamoxifen, many antidepressants",
        "CYP2C9":  "Warfarin, NSAIDs, sulfonylureas",
        "SLCO1B1": "Statin myopathy risk",
        "VKORC1":  "Warfarin dose requirement",
        "MTHFR":   "Folate metabolism, homocysteine",
        "DPYD":    "Fluorouracil / capecitabine safety",
    }

    for gene, result in phenotypes.items():
        label = result.get("label", "Unknown")
        is_normal = "normal" in result.get("phenotype", "").lower()
        icon = "✅" if is_normal else "⚠️"
        lines.append(f"| {gene} | {icon} {label} | {gene_relevance.get(gene, '')} |")

    lines.append("")

    # Detailed phenotype findings
    lines.append("## Detailed findings\n")
    for gene, result in phenotypes.items():
        is_normal = "normal" in result.get("phenotype", "").lower()
        if is_normal:
            continue  # Only show non-normal genes in detail
        lines.append(f"### {gene} — {result['label']}\n")
        lines.append(f"{result.get('implication', '')}\n")

    # Medication alerts
    if alerts:
        lines.append("## Medication implications\n")
        icons = {"critical": "🔴", "major": "🟠", "moderate": "🟡"}
        for a in alerts:
            icon = icons.get(a["severity"], "⚪")
            lines.append(
                f"### {icon} {a['severity'].upper()}: {a['gene']} × "
                f"{', '.join(a['medications'])}\n"
            )
            lines.append(f"{a['message']}\n")
    else:
        lines.append("## Medication implications\n")
        lines.append(
            "✅ No significant interactions detected between your pharmacogenomic profile "
            "and your current medications.\n"
        )

    lines.append(
        "_Always discuss pharmacogenomic findings with your prescriber or a clinical pharmacist "
        "before changing any medications._\n"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_pgx_file(root: Path, person_id: str, pgx_path: Path) -> dict[str, Any]:
    """Parse a 23andMe/AncestryDNA file and store PGx results in the profile.

    Returns: {variants_found, phenotypes, alerts_count}
    """
    if not pgx_path.exists():
        raise FileNotFoundError(pgx_path)

    variants = parse_raw_genotype_file(pgx_path)
    if not variants:
        raise ValueError(
            f"No pharmacogenomic variants found in {pgx_path.name}. "
            "Is this a 23andMe or AncestryDNA raw data file?"
        )

    phenotypes = call_all_phenotypes(variants)

    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        medications = profile.get("medications") or []
        alerts = pgx_drug_alerts(phenotypes, medications)

        # Store PGx results in profile
        profile["pharmacogenomics"] = {
            "source_file": pgx_path.name,
            "variants_analysed": len(variants),
            "phenotypes": {gene: p["phenotype"] for gene, p in phenotypes.items()},
            "phenotype_labels": {gene: p["label"] for gene, p in phenotypes.items()},
            "alerts_count": len(alerts),
        }
        save_profile(root, person_id, profile)

    # Write report
    report_text = render_pgx_report(phenotypes, alerts, len(variants))
    report_path = pgx_report_path(root, person_id)
    atomic_write_text(report_path, report_text)

    return {
        "variants_found": len(variants),
        "phenotypes": {gene: p["phenotype"] for gene, p in phenotypes.items()},
        "alerts_count": len(alerts),
        "report_path": str(report_path),
    }
