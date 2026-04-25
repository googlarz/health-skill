# Photo Handling

Health Skill accepts photos as a first-class input. When a user pastes or attaches a photo, identify the type and follow the matching protocol below. Always store the image in `inbox/` (or `Archive/` after processing) and produce a structured note.

## Photo types and protocols

### 1. Posture photo (side or back view)

**Goal:** identify visible postural deviations and offer corrective exercises. Not a diagnosis.

Look for:
- **Side view**: forward head, rounded shoulders (kyphosis), anterior pelvic tilt (lordosis), posterior pelvic tilt, knee position relative to ankles
- **Back view**: shoulder height asymmetry, hip height asymmetry, scapular winging, lateral lean
- **Front view**: foot pronation, knee valgus/varus

Output:
1. What you observe (1–3 visible deviations, ranked by significance)
2. What it commonly relates to (tight chest, weak rear delts, etc.)
3. 3–5 corrective exercises from `scripts/training.py` exercise bank
4. When to see a physical therapist (pain, persistent asymmetry, neurological symptoms)

Save: `notes/{date}-posture-analysis.md` with the observations and recommended program.

### 2. Skin / wound / rash photo

**Goal:** describe what is visible and triage urgency. Never diagnose skin cancer or specific dermatologic conditions.

Look for and describe:
- Size, shape, border (regular vs irregular), colour (uniform vs mixed)
- Symmetry / asymmetry (ABCDE for moles: Asymmetry, Border, Colour, Diameter, Evolution)
- Surrounding skin (redness, swelling, warmth indicators)
- Wound: edges, drainage, signs of infection

Escalate to **urgent** when:
- Rapid expansion, dark/multi-coloured, new bleeding
- Wound: red streaks, pus, fever, increasing pain
- Allergic reaction with face/lip/tongue swelling — **emergency**

Always end with: "I can describe what I see, but a clinician must confirm. Photos are not diagnostic."

Save: `notes/{date}-skin-photo-{location}.md`.

### 3. Medication bottle / packaging

**Goal:** read the label, add to medication list with provenance, check allergy conflicts.

Extract:
- Drug name (generic and brand)
- Dose and unit
- Frequency / instructions
- Prescriber if visible
- Refills and expiry

Then:
1. Run allergy conflict check (`care_workspace.find_medication_allergy_conflicts`)
2. Surface common interactions with existing medications
3. Add to review queue at `needs_quick_confirmation` tier
4. Save to `notes/{date}-medication-{name}.md`

### 4. Lab report screenshot or photo of paper labs

**Goal:** OCR the values, route through the standard extraction pipeline.

1. Read every visible test name, value, unit, reference range, and flag
2. Save raw text to `inbox/{date}-lab-photo.txt` so `process_inbox` can ingest
3. Mark provenance as `photo_extraction` (lower trust than digital PDF)
4. All extracted labs go to `HEALTH_REVIEW_QUEUE.json` for confirmation, never auto-apply

### 5. Food photo

**Goal:** rough macro estimate to support training/longevity goals. Not a precise tracker.

Provide:
- Identified items
- Approximate portion size
- Rough calorie range (e.g., "350–450 kcal")
- Estimated protein (relevant for menopause / strength training)
- Comments on protein adequacy if a daily target is set

Do not provide false precision. If the photo is ambiguous, ask.

### 6. Progress / body composition photo

**Goal:** longitudinal comparison, not body-image judgement.

- Compare against the most recent photo if one exists
- Note observable changes (muscle definition, posture, swelling)
- Tie to recent training and weight data
- Be neutral and supportive — never aesthetic critique

## Universal rules

- Photos contain identifying information. Treat as private. Do not transmit.
- Save originals to `Archive/{date}-{type}-photo.{ext}`.
- Always produce a structured note alongside.
- Never claim the photo is diagnostic.
- If the user looks unwell in any photo (e.g., visible swelling, jaundice, distress), surface that and recommend clinician contact.
