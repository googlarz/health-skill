#!/usr/bin/env python3
"""Menopause and hormonal health companion for Health Skill.

Covers perimenopause, menopause, and post-menopause:
- Symptom tracking and pattern analysis
- HRT context (estrogen, progesterone, testosterone)
- Exercise guidance optimized for bone density and muscle mass
- Lab interpretation (FSH, LH, estradiol, SHBG, lipids, bone markers)
- Escalation triggers
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Menopause stage classification
# ---------------------------------------------------------------------------

STAGE_RULES = {
    "perimenopause": {
        "description": "Transition phase — cycles becoming irregular, hormone levels fluctuating.",
        "typical_age_range": "40–52",
        "key_labs": ["FSH", "LH", "Estradiol", "SHBG"],
        "note": "FSH > 10 IU/L with irregular cycles often suggests perimenopause but cannot confirm alone.",
    },
    "menopause": {
        "description": "12 consecutive months without a period.",
        "typical_age_range": "45–55 (median 51)",
        "key_labs": ["FSH", "LH", "Estradiol"],
        "note": "FSH > 40 IU/L and Estradiol < 30 pg/mL are consistent with menopause; clinician confirms.",
    },
    "post_menopause": {
        "description": "All years after the 12-month mark.",
        "typical_age_range": "51+",
        "key_labs": ["FSH", "Estradiol", "SHBG", "Total Testosterone", "Bone markers (CTX, P1NP)", "Lipid panel"],
        "note": "Bone density and cardiovascular risk rise. DEXA and lipid monitoring become more important.",
    },
}


# ---------------------------------------------------------------------------
# Symptom catalogue
# ---------------------------------------------------------------------------

MENOPAUSE_SYMPTOMS: dict[str, dict[str, Any]] = {
    "hot_flashes": {
        "aliases": ["hot flash", "hot flushes", "flush", "night sweats"],
        "phase": ["perimenopause", "menopause", "post_menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["venlafaxine", "gabapentin", "clonidine", "CBT", "cooling techniques"],
        "log_note": "Rate severity 1–10. Track frequency per day.",
    },
    "sleep_disruption": {
        "aliases": ["can't sleep", "insomnia", "poor sleep", "waking at night", "sleep problems"],
        "phase": ["perimenopause", "menopause", "post_menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["sleep hygiene", "magnesium glycinate", "CBT-I"],
        "log_note": "Often secondary to night sweats. Track separately.",
    },
    "mood_changes": {
        "aliases": ["mood", "irritable", "irritability", "anxiety", "depression", "low mood", "brain fog", "foggy"],
        "phase": ["perimenopause", "menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["therapy", "exercise", "SSRI/SNRI if indicated by clinician"],
        "log_note": "Distinguish from pre-existing mood disorder. Track alongside cycle data.",
    },
    "joint_pain": {
        "aliases": ["joint pain", "joint ache", "arthralgia", "aches", "muscle aches"],
        "phase": ["perimenopause", "menopause", "post_menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["strength training", "omega-3", "anti-inflammatory diet"],
        "log_note": "Estrogen has anti-inflammatory effects. Worsening joint pain is common in transition.",
    },
    "vaginal_dryness": {
        "aliases": ["vaginal dryness", "dryness", "urogenital", "painful sex", "GSM"],
        "phase": ["menopause", "post_menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["topical estrogen (low-risk)", "vaginal moisturizers", "lubricants"],
        "log_note": "Genitourinary syndrome of menopause (GSM). Local estrogen is effective and low-risk.",
    },
    "weight_gain": {
        "aliases": ["weight", "gaining weight", "abdominal weight", "belly fat"],
        "phase": ["perimenopause", "menopause", "post_menopause"],
        "hrt_responsive": False,
        "non_hrt_options": ["strength training", "protein intake ≥1.2g/kg", "sleep", "stress reduction"],
        "log_note": "Visceral fat increases with estrogen decline. Resistance training is first-line.",
    },
    "brain_fog": {
        "aliases": ["brain fog", "memory", "concentration", "focus", "forgetful", "foggy"],
        "phase": ["perimenopause", "menopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["sleep improvement", "exercise", "stress reduction"],
        "log_note": "Usually transient. Persistent cognitive symptoms warrant clinician evaluation.",
    },
    "palpitations": {
        "aliases": ["palpitations", "heart racing", "heart pounding"],
        "phase": ["perimenopause"],
        "hrt_responsive": True,
        "non_hrt_options": ["reduce caffeine and alcohol", "stress management"],
        "log_note": "Rule out cardiac cause first — see clinician if frequent or with chest pain.",
        "escalate_if": "palpitations with chest pain, shortness of breath, or syncope → urgent evaluation",
    },
}


# ---------------------------------------------------------------------------
# HRT knowledge base
# ---------------------------------------------------------------------------

HRT_TYPES: dict[str, dict[str, Any]] = {
    "estrogen": {
        "forms": ["oral", "patch", "gel", "spray", "vaginal ring"],
        "primary_indications": ["hot flashes", "sleep", "mood", "bone protection", "vaginal dryness", "joint pain"],
        "key_benefit": "Most effective for vasomotor symptoms and bone density.",
        "note": "Women with a uterus need progesterone added to protect the uterine lining.",
        "labs_to_monitor": ["Estradiol", "Lipid panel (annually)", "Liver function (oral estrogen)"],
        "bone_benefit": True,
        "cardiovascular_note": "Transdermal estrogen has lower clot risk than oral estrogen.",
    },
    "progesterone": {
        "forms": ["oral (micronized)", "Mirena IUD", "synthetic progestins"],
        "primary_indications": ["uterine protection with estrogen", "sleep (oral micronized progesterone)"],
        "key_benefit": "Micronized progesterone (Utrogestan/Prometrium) has a better safety profile than synthetic progestins.",
        "note": "Oral micronized progesterone also improves sleep quality.",
        "labs_to_monitor": [],
        "bone_benefit": False,
    },
    "testosterone": {
        "forms": ["gel", "cream (compounded)", "patch"],
        "primary_indications": ["low libido", "energy", "muscle mass", "mood", "brain fog"],
        "key_benefit": "Emerging evidence for libido, energy, and possibly bone in post-menopausal women.",
        "note": "Not FDA-approved for women in many countries but widely prescribed off-label. Clinician supervision required.",
        "labs_to_monitor": ["Total Testosterone", "SHBG", "Free Testosterone", "Hematocrit"],
        "bone_benefit": False,
    },
    "tibolone": {
        "forms": ["oral"],
        "primary_indications": ["combined estrogenic/progestogenic/androgenic activity"],
        "key_benefit": "Single pill alternative; also improves libido.",
        "note": "Not available in the US; used in Europe and Australia.",
        "labs_to_monitor": ["Lipid panel"],
        "bone_benefit": True,
    },
    "topical_estrogen": {
        "forms": ["vaginal cream", "vaginal ring", "vaginal tablet"],
        "primary_indications": ["vaginal dryness", "UTIs", "GSM"],
        "key_benefit": "Very low systemic absorption. Safe for most women including those with hormone-sensitive cancer history (discuss with oncologist).",
        "note": "Does NOT require progesterone to protect the uterus at standard doses.",
        "labs_to_monitor": [],
        "bone_benefit": False,
    },
}


# ---------------------------------------------------------------------------
# Lab interpretation for hormonal health
# ---------------------------------------------------------------------------

HORMONAL_LABS: dict[str, dict[str, Any]] = {
    "FSH": {
        "full_name": "Follicle-Stimulating Hormone",
        "units": "IU/L",
        "interpretations": {
            "perimenopause_signal": "> 10 IU/L with irregular cycles",
            "menopause_consistent": "> 40 IU/L",
        },
        "caveat": "FSH fluctuates widely in perimenopause. One reading is not diagnostic.",
    },
    "LH": {
        "full_name": "Luteinizing Hormone",
        "units": "IU/L",
        "interpretations": {
            "elevated_post_menopause": "> 20 IU/L",
        },
        "caveat": "Elevated LH with elevated FSH and low estradiol confirms menopause.",
    },
    "Estradiol": {
        "full_name": "Estradiol (E2)",
        "units": "pg/mL",
        "interpretations": {
            "post_menopause_typical": "< 30 pg/mL",
            "therapeutic_range_on_hrt": "40–200 pg/mL (varies by symptoms and delivery method)",
        },
        "caveat": "Target range on HRT is symptom-guided, not a strict number.",
    },
    "SHBG": {
        "full_name": "Sex Hormone-Binding Globulin",
        "units": "nmol/L",
        "interpretations": {
            "high": "Lowers free testosterone — may contribute to low libido on oral estrogen.",
            "low": "More free testosterone available.",
        },
        "caveat": "Oral estrogen raises SHBG more than transdermal. Relevant when evaluating testosterone levels.",
    },
    "Total Testosterone": {
        "full_name": "Total Testosterone",
        "units": "ng/dL or nmol/L",
        "interpretations": {
            "female_normal_range": "15–70 ng/dL (varies by lab)",
            "low": "< 15 ng/dL — may be associated with low libido, fatigue, muscle loss",
        },
        "caveat": "Free testosterone is more clinically useful; SHBG context matters.",
    },
    "CTX": {
        "full_name": "C-terminal telopeptide (bone resorption marker)",
        "units": "ng/L",
        "interpretations": {
            "elevated": "Bone breakdown accelerated — consider DEXA if not recent",
        },
        "caveat": "Levels fluctuate with fasting state. Best collected fasting AM.",
    },
    "P1NP": {
        "full_name": "Procollagen type 1 N-terminal propeptide (bone formation marker)",
        "units": "ng/mL",
        "interpretations": {
            "use": "Tracks bone turnover response to treatment (bisphosphonates, HRT).",
        },
        "caveat": "Used alongside DEXA to monitor bone health response.",
    },
}


# ---------------------------------------------------------------------------
# Exercise guidance for menopause
# ---------------------------------------------------------------------------

MENOPAUSE_EXERCISE_PRINCIPLES = """
## Exercise priorities for perimenopause and post-menopause

### 1. Resistance / strength training (FIRST priority)
- **Why**: Estrogen loss accelerates muscle loss (sarcopenia) and bone density decline.
  Resistance training is the most effective countermeasure.
- **Minimum effective dose**: 2–3 sessions/week, 8–12 reps, progressive overload.
- **Best exercises**: Compound movements — squats, deadlifts, hip thrusts, rows, overhead press.
  These load multiple muscle groups and stimulate bone more effectively than isolation exercises.
- **Bone-loading principle**: Bone responds to impact and load. Weight-bearing compound lifts
  (not just swimming or cycling) are required for bone density benefit.
- **Practical start**: Goblet squat, Romanian deadlift, hip thrust, seated row, overhead press.

### 2. Impact / plyometric work (bone density)
- Even low-impact jumping (jump rope, jump squats) stimulates bone in a way steady-state cardio does not.
- Minimum: 10–20 impact reps 3×/week alongside strength training.

### 3. Cardiovascular training (secondary, not first)
- Important for cardiovascular risk (which rises post-menopause) and mood.
- Steady-state cardio alone does NOT protect bone or maintain muscle mass.
- Zone 2 cardio (brisk walk, light jog, cycling) 2–3×/week is a useful complement.

### 4. Protein intake
- Target: ≥1.2–1.6 g/kg body weight/day to support muscle protein synthesis.
- Distribute across meals; post-workout window is real but total daily intake matters more.

### 5. Recovery and sleep
- Cortisol rises with sleep deprivation → further muscle catabolism.
- Prioritize 7–9h sleep. Hot flash management (via HRT or non-hormonal options) directly
  improves training adaptations.

### Red flags during exercise
- New chest pain or palpitations → stop and seek evaluation
- Joint pain with swelling or warmth → reduce load and see clinician
- Bone pain after impact → rule out stress fracture (especially if DEXA shows osteoporosis)
"""


# ---------------------------------------------------------------------------
# Escalation triggers
# ---------------------------------------------------------------------------

MENOPAUSE_ESCALATION_TRIGGERS = [
    "Palpitations with chest pain, shortness of breath, or fainting",
    "Sudden severe headache during HRT (rule out thrombosis)",
    "Unilateral leg swelling or pain on HRT (DVT risk)",
    "Postmenopausal bleeding (any vaginal bleeding after 12-month amenorrhea)",
    "Breast lump or nipple discharge",
    "Fracture from minor trauma (osteoporosis screening overdue)",
    "Rapid cognitive decline (not typical brain fog)",
    "Persistent depression or suicidal ideation",
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def identify_menopause_symptoms(text: str) -> list[str]:
    """Return list of menopause symptom keys found in a free-text string."""
    low = text.lower()
    found: list[str] = []
    for key, info in MENOPAUSE_SYMPTOMS.items():
        aliases: list[str] = [key.replace("_", " ")] + info.get("aliases", [])
        if any(alias in low for alias in aliases):
            found.append(key)
    return found


def hrt_context(hrt_type: str) -> dict[str, Any] | None:
    """Return HRT information for a given type string (fuzzy match)."""
    key = hrt_type.lower().replace(" ", "_").replace("-", "_")
    if key in HRT_TYPES:
        return HRT_TYPES[key]
    # Partial match
    for k, v in HRT_TYPES.items():
        if key in k or k in key:
            return v
    return None


def lab_context(lab_name: str) -> dict[str, Any] | None:
    """Return hormonal lab context for a lab name (fuzzy match)."""
    normalized = lab_name.strip()
    if normalized in HORMONAL_LABS:
        return HORMONAL_LABS[normalized]
    low = normalized.lower()
    for k, v in HORMONAL_LABS.items():
        if low in k.lower() or k.lower() in low:
            return v
    return None


def menopause_exercise_guidance() -> str:
    """Return exercise principles as formatted text."""
    return MENOPAUSE_EXERCISE_PRINCIPLES.strip()


def check_escalation(text: str) -> list[str]:
    """Return list of escalation triggers matched in free text."""
    low = text.lower()
    triggered: list[str] = []
    trigger_keywords = [
        ("palpitations", MENOPAUSE_ESCALATION_TRIGGERS[0]),
        ("severe headache", MENOPAUSE_ESCALATION_TRIGGERS[1]),
        ("leg swelling", MENOPAUSE_ESCALATION_TRIGGERS[2]),
        ("postmenopausal bleeding", MENOPAUSE_ESCALATION_TRIGGERS[3]),
        ("breast lump", MENOPAUSE_ESCALATION_TRIGGERS[4]),
        ("fracture", MENOPAUSE_ESCALATION_TRIGGERS[5]),
    ]
    for kw, trigger in trigger_keywords:
        if kw in low:
            triggered.append(trigger)
    return triggered
