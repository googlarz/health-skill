#!/usr/bin/env python3
"""Drug-drug and drug-condition interaction checker.

Covers the most clinically significant interactions. Each entry has:
- severity: critical / major / moderate
- mechanism: why it happens (one sentence)
- effect: what can go wrong
- action: what to do about it

Usage:
    from interactions import check_interactions
    alerts = check_interactions(profile)
    for a in alerts:
        print(a["summary"])
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Interaction database
# Each entry: drugs (list of name fragments to match), conditions (optional),
# severity, effect, action, mechanism
# A match fires when ANY drug in slot A and ANY drug in slot B are both present.
# ---------------------------------------------------------------------------

DRUG_DRUG: list[dict[str, Any]] = [
    # ── Bleeding risk ────────────────────────────────────────────────────────
    {
        "a": ["warfarin", "coumadin"],
        "b": ["ibuprofen", "naproxen", "aspirin", "diclofenac", "celecoxib", "nsaid",
              "indomethacin", "ketorolac", "meloxicam"],
        "severity": "critical",
        "effect": "Significantly increased bleeding risk — GI bleed or intracranial haemorrhage",
        "action": "Avoid NSAIDs with warfarin if possible. Use paracetamol/acetaminophen instead. Monitor INR closely if unavoidable.",
        "mechanism": "NSAIDs inhibit platelet function and damage the gastric mucosa; combined with warfarin's anticoagulation, bleeding risk multiplies.",
    },
    {
        "a": ["warfarin", "coumadin"],
        "b": ["amiodarone", "cordarone"],
        "severity": "critical",
        "effect": "Amiodarone markedly potentiates warfarin — INR can double or triple",
        "action": "Reduce warfarin dose by 30–50% when starting amiodarone. Monitor INR every 3–5 days for first 3 weeks.",
        "mechanism": "Amiodarone and its metabolite desethylamiodarone inhibit CYP2C9, slowing warfarin metabolism.",
    },
    {
        "a": ["warfarin", "coumadin"],
        "b": ["fluconazole", "metronidazole", "flagyl", "ciprofloxacin", "trimethoprim",
              "sulfamethoxazole", "clarithromycin", "erythromycin"],
        "severity": "major",
        "effect": "INR elevation — increased bleeding risk",
        "action": "Monitor INR within 3–5 days of starting the antibiotic. May need warfarin dose reduction.",
        "mechanism": "These antibiotics inhibit CYP2C9/CYP3A4 (slowing warfarin breakdown) or reduce gut bacteria that synthesise vitamin K.",
    },
    # ── Serotonin syndrome ───────────────────────────────────────────────────
    {
        "a": ["ssri", "sertraline", "fluoxetine", "escitalopram", "citalopram", "paroxetine",
              "fluvoxamine", "venlafaxine", "duloxetine", "snri"],
        "b": ["maoi", "phenelzine", "tranylcypromine", "selegiline", "rasagiline",
              "linezolid", "methylene blue"],
        "severity": "critical",
        "effect": "Serotonin syndrome — potentially fatal: agitation, confusion, rapid heart rate, high BP, hyperthermia, seizures",
        "action": "This combination is contraindicated. Allow ≥14 days washout after stopping an MAOI before starting an SSRI (≥5 weeks after fluoxetine).",
        "mechanism": "Both drug classes increase serotonergic transmission; combined, serotonin accumulates to toxic levels.",
    },
    {
        "a": ["ssri", "sertraline", "fluoxetine", "escitalopram", "citalopram", "paroxetine",
              "snri", "venlafaxine", "duloxetine"],
        "b": ["triptan", "sumatriptan", "rizatriptan", "zolmitriptan", "eletriptan"],
        "severity": "major",
        "effect": "Serotonin syndrome risk — agitation, rapid heart rate, tremor",
        "action": "Use with caution. Watch for serotonin syndrome symptoms (especially in first weeks). Consider alternative migraine treatment.",
        "mechanism": "Triptans are serotonin receptor agonists; SSRIs increase synaptic serotonin.",
    },
    # ── QT prolongation ─────────────────────────────────────────────────────
    {
        "a": ["amiodarone", "sotalol", "dronedarone"],
        "b": ["azithromycin", "clarithromycin", "erythromycin", "levofloxacin",
              "moxifloxacin", "ciprofloxacin", "haloperidol", "quetiapine",
              "methadone", "ondansetron", "domperidone"],
        "severity": "major",
        "effect": "Additive QT prolongation — risk of torsades de pointes (life-threatening arrhythmia)",
        "action": "Avoid combination where possible. If necessary, obtain baseline ECG and monitor QTc interval. Correct electrolytes.",
        "mechanism": "Both drug classes block cardiac hERG potassium channels, prolonging ventricular repolarisation.",
    },
    # ── Statins ──────────────────────────────────────────────────────────────
    {
        "a": ["statin", "simvastatin", "lovastatin", "atorvastatin", "rosuvastatin",
              "pravastatin", "fluvastatin"],
        "b": ["clarithromycin", "erythromycin", "azithromycin", "itraconazole",
              "ketoconazole", "fluconazole", "cyclosporine", "gemfibrozil"],
        "severity": "major",
        "effect": "Elevated statin blood levels — risk of myopathy or rhabdomyolysis (muscle breakdown)",
        "action": "Avoid simvastatin/lovastatin with strong CYP3A4 inhibitors. Switch to pravastatin or rosuvastatin (less CYP3A4 dependent) if antibiotic course needed.",
        "mechanism": "These drugs inhibit CYP3A4, the enzyme that metabolises most statins, causing statin accumulation.",
    },
    {
        "a": ["statin", "simvastatin", "lovastatin", "atorvastatin", "rosuvastatin"],
        "b": ["amiodarone"],
        "severity": "moderate",
        "effect": "Increased statin levels — myopathy risk",
        "action": "Limit simvastatin to 20mg/day with amiodarone. Consider rosuvastatin or pravastatin.",
        "mechanism": "Amiodarone inhibits CYP3A4 and P-glycoprotein.",
    },
    # ── Metformin ────────────────────────────────────────────────────────────
    {
        "a": ["metformin"],
        "b": ["contrast", "iodinated contrast", "ct contrast", "angiogram"],
        "severity": "major",
        "effect": "Contrast-induced nephropathy can cause metformin accumulation → lactic acidosis",
        "action": "Hold metformin 48h before and after iodinated contrast procedures. Resume only if renal function is stable.",
        "mechanism": "Contrast agents can cause acute kidney injury; metformin is renally cleared and accumulates if kidneys fail.",
    },
    # ── ACE inhibitors / ARBs ────────────────────────────────────────────────
    {
        "a": ["ace inhibitor", "lisinopril", "ramipril", "enalapril", "perindopril",
              "captopril", "arb", "losartan", "valsartan", "candesartan", "olmesartan"],
        "b": ["ibuprofen", "naproxen", "nsaid", "indomethacin", "diclofenac", "celecoxib"],
        "severity": "major",
        "effect": "Reduced antihypertensive effect + acute kidney injury risk",
        "action": "Avoid regular NSAIDs with ACE inhibitors/ARBs. Use paracetamol for pain. Monitor kidney function if combination unavoidable.",
        "mechanism": "NSAIDs blunt the renal vasodilatory prostaglandins that ACE inhibitors/ARBs rely on, impairing kidney perfusion.",
    },
    {
        "a": ["ace inhibitor", "lisinopril", "ramipril", "enalapril", "captopril",
              "arb", "losartan", "valsartan"],
        "b": ["potassium", "spironolactone", "eplerenone", "triamterene", "amiloride"],
        "severity": "major",
        "effect": "Hyperkalaemia (dangerously high potassium) — cardiac arrhythmia risk",
        "action": "Monitor potassium levels regularly. Avoid potassium supplements unless hypokalaemia is confirmed.",
        "mechanism": "ACE inhibitors/ARBs retain potassium; potassium-sparing diuretics and supplements add to the load.",
    },
    # ── Thyroid ──────────────────────────────────────────────────────────────
    {
        "a": ["levothyroxine", "synthroid", "eltroxin"],
        "b": ["calcium", "iron", "ferrous sulfate", "antacid", "ppi", "omeprazole",
              "pantoprazole", "sucralfate", "cholestyramine", "colestipol"],
        "severity": "moderate",
        "effect": "Reduced levothyroxine absorption — hypothyroid symptoms may return",
        "action": "Take levothyroxine on an empty stomach, 30–60 minutes before these medications. Separate by at least 4 hours where possible.",
        "mechanism": "These substances bind levothyroxine in the gut, reducing absorption by 20–40%.",
    },
    # ── Clopidogrel ──────────────────────────────────────────────────────────
    {
        "a": ["clopidogrel", "plavix"],
        "b": ["omeprazole", "esomeprazole", "pantoprazole", "ppi"],
        "severity": "moderate",
        "effect": "Reduced clopidogrel effectiveness — less platelet inhibition",
        "action": "Use pantoprazole (lowest CYP2C19 inhibition) if a PPI is needed with clopidogrel. Avoid omeprazole/esomeprazole.",
        "mechanism": "Clopidogrel is a prodrug requiring CYP2C19 activation; omeprazole/esomeprazole inhibit this enzyme.",
    },
    # ── Digoxin ──────────────────────────────────────────────────────────────
    {
        "a": ["digoxin", "digitalis"],
        "b": ["amiodarone", "verapamil", "diltiazem", "clarithromycin",
              "erythromycin", "quinidine", "itraconazole"],
        "severity": "major",
        "effect": "Digoxin toxicity — nausea, bradycardia, visual disturbances, arrhythmia",
        "action": "Reduce digoxin dose by 50% when adding amiodarone. Monitor digoxin levels. Watch for toxicity symptoms.",
        "mechanism": "These drugs increase digoxin levels by inhibiting P-glycoprotein (its transporter) or displacing it from tissue binding.",
    },
    # ── Lithium ──────────────────────────────────────────────────────────────
    {
        "a": ["lithium"],
        "b": ["ibuprofen", "naproxen", "nsaid", "diclofenac", "celecoxib"],
        "severity": "major",
        "effect": "Lithium toxicity — tremor, confusion, kidney damage",
        "action": "Avoid NSAIDs with lithium. Use paracetamol for pain. Check lithium levels if unavoidable.",
        "mechanism": "NSAIDs reduce renal prostaglandins, decreasing lithium excretion and raising blood levels by 20–60%.",
    },
    {
        "a": ["lithium"],
        "b": ["ace inhibitor", "lisinopril", "ramipril", "enalapril",
              "arb", "losartan", "valsartan", "thiazide", "hydrochlorothiazide"],
        "severity": "major",
        "effect": "Lithium toxicity — reduced renal clearance causes accumulation",
        "action": "Monitor lithium levels closely when starting or changing these medications.",
        "mechanism": "ACE inhibitors, ARBs, and thiazides reduce renal blood flow or sodium excretion, both of which reduce lithium clearance.",
    },
    # ── Methotrexate ─────────────────────────────────────────────────────────
    {
        "a": ["methotrexate"],
        "b": ["ibuprofen", "naproxen", "nsaid", "diclofenac", "aspirin", "trimethoprim",
              "sulfamethoxazole", "penicillin", "probenecid"],
        "severity": "major",
        "effect": "Methotrexate toxicity — bone marrow suppression, mucositis, kidney damage",
        "action": "Avoid NSAIDs and sulfa drugs with methotrexate if possible. If unavoidable, monitor full blood count and renal function closely.",
        "mechanism": "These drugs compete with methotrexate for renal tubular secretion, increasing methotrexate levels significantly.",
    },
    # ── Beta-blockers ─────────────────────────────────────────────────────────
    {
        "a": ["beta-blocker", "metoprolol", "atenolol", "bisoprolol", "carvedilol",
              "propranolol", "nebivolol"],
        "b": ["verapamil", "diltiazem"],
        "severity": "major",
        "effect": "Heart block and severe bradycardia — risk of cardiac arrest",
        "action": "This combination requires cardiac monitoring. Avoid IV verapamil in patients on beta-blockers. Use with extreme caution.",
        "mechanism": "Both drug classes slow conduction through the AV node; combined, they can block conduction entirely.",
    },
    # ── Supplements ──────────────────────────────────────────────────────────
    {
        "a": ["biotin"],
        "b": ["levothyroxine"],
        "severity": "moderate",
        "effect": "Biotin >5mg/day can falsely lower TSH and falsely elevate T4/T3 on immunoassay — looks like hyperthyroidism",
        "action": "Stop biotin at least 48 hours before thyroid blood tests. Inform your lab if you take biotin.",
        "mechanism": "Biotin interferes with streptavidin-biotin immunoassay technology used in most thyroid tests.",
    },
    {
        "a": ["st. john's wort", "hypericum"],
        "b": ["ssri", "sertraline", "fluoxetine", "escitalopram", "citalopram",
              "warfarin", "contraceptive", "oral contraceptive", "pill",
              "cyclosporine", "digoxin", "hiv", "antiretroviral"],
        "severity": "major",
        "effect": "St. John's Wort induces liver enzymes, significantly reducing levels of many medications",
        "action": "Avoid St. John's Wort with any of these medications. Inform your prescriber if using it.",
        "mechanism": "St. John's Wort is a potent inducer of CYP3A4 and P-glycoprotein, accelerating the metabolism of many drugs.",
    },
]

# Drug-condition interactions (e.g., metformin in renal impairment)
DRUG_CONDITION: list[dict[str, Any]] = [
    {
        "medication": ["metformin"],
        "condition": ["kidney disease", "ckd", "renal impairment"],
        "severity": "major",
        "effect": "Metformin contraindicated in severe renal impairment (eGFR <30) — lactic acidosis risk",
        "action": "Reduce dose if eGFR 30–45. Stop if eGFR <30. Discuss with prescriber.",
    },
    {
        "medication": ["nsaid", "ibuprofen", "naproxen", "diclofenac"],
        "condition": ["kidney disease", "ckd", "heart failure", "hypertension"],
        "severity": "major",
        "effect": "NSAIDs worsen kidney function, raise blood pressure, and increase heart failure hospitalisation",
        "action": "Avoid regular NSAIDs. Use paracetamol for pain. Discuss with prescriber.",
    },
    {
        "medication": ["warfarin", "coumadin"],
        "condition": ["liver disease", "hepatitis", "cirrhosis"],
        "severity": "major",
        "effect": "Liver disease impairs clotting factor synthesis, making warfarin dose highly unpredictable",
        "action": "INR monitoring must be more frequent. Dose adjustment likely needed.",
    },
]


def _med_matches(med_name: str, keywords: list[str]) -> bool:
    n = med_name.lower()
    return any(kw in n or n.startswith(kw) for kw in keywords)


def _any_med_matches(medications: list[dict[str, Any]], keywords: list[str]) -> list[str]:
    return [
        m.get("name", "?")
        for m in medications
        if _med_matches(m.get("name", ""), keywords)
    ]


def _condition_present(conditions: list[dict[str, Any]], keywords: list[str]) -> bool:
    for c in conditions:
        name = (c.get("name") or "").lower()
        if any(kw in name for kw in keywords):
            return True
    return False


def check_interactions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Check for drug-drug and drug-condition interactions in the profile.

    Returns a list of interaction alerts, sorted by severity (critical first).
    """
    medications = profile.get("medications") or []
    conditions = profile.get("conditions") or []
    alerts: list[dict[str, Any]] = []

    # Drug-drug interactions
    for rule in DRUG_DRUG:
        matched_a = _any_med_matches(medications, rule["a"])
        matched_b = _any_med_matches(medications, rule["b"])
        if matched_a and matched_b:
            alerts.append({
                "type": "drug-drug",
                "severity": rule["severity"],
                "drugs": matched_a + matched_b,
                "effect": rule["effect"],
                "action": rule["action"],
                "mechanism": rule.get("mechanism", ""),
                "summary": (
                    f"[{rule['severity'].upper()}] {' + '.join(matched_a + matched_b)}: "
                    f"{rule['effect']}"
                ),
            })

    # Drug-condition interactions
    for rule in DRUG_CONDITION:
        matched_meds = _any_med_matches(medications, rule["medication"])
        if matched_meds and _condition_present(conditions, rule["condition"]):
            alerts.append({
                "type": "drug-condition",
                "severity": rule["severity"],
                "drugs": matched_meds,
                "effect": rule["effect"],
                "action": rule["action"],
                "mechanism": "",
                "summary": (
                    f"[{rule['severity'].upper()}] {' + '.join(matched_meds)} with "
                    f"{rule['condition'][0]}: {rule['effect']}"
                ),
            })

    # Sort: critical → major → moderate
    order = {"critical": 0, "major": 1, "moderate": 2}
    alerts.sort(key=lambda a: order.get(a["severity"], 3))
    return alerts


def render_interactions_text(profile: dict[str, Any]) -> str:
    alerts = check_interactions(profile)
    if not alerts:
        return (
            "# Medication Interactions\n\n"
            "✅ No significant drug-drug or drug-condition interactions detected "
            "in your current medication list.\n\n"
            "_Note: This check covers common clinically significant interactions. "
            "Always confirm with your pharmacist or prescriber._\n"
        )

    lines = ["# Medication Interactions\n"]
    lines.append(f"Found **{len(alerts)}** interaction(s) to review:\n")

    icons = {"critical": "🔴", "major": "🟠", "moderate": "🟡"}
    for a in alerts:
        icon = icons.get(a["severity"], "⚪")
        lines.append(f"## {icon} {a['severity'].upper()}: {' + '.join(a['drugs'])}\n")
        lines.append(f"**Effect:** {a['effect']}\n")
        lines.append(f"**What to do:** {a['action']}\n")
        if a.get("mechanism"):
            lines.append(f"**Why it happens:** {a['mechanism']}\n")
        lines.append("")

    lines.append(
        "_This check covers common clinically significant interactions. "
        "Always confirm with your pharmacist or prescriber before making changes._\n"
    )
    return "\n".join(lines)
