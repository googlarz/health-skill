# Demo Workspace: Karen Mitchell

This is a pre-populated Health Skill workspace showing what a real person folder looks like after a few months of use.

## Karen's profile

- **Age**: 57, female
- **Conditions**: Hyperlipidemia, Essential Hypertension, Vitamin D Deficiency
- **Medications**: Atorvastatin 20mg, Lisinopril 10mg, Vitamin D3 2000 IU
- **Allergies**: Sulfa drugs (hives), Shellfish (throat swelling — life-threatening)
- **Clinicians**: Dr. Sarah Chen (PCP), Dr. James Park (Cardiologist)

## What to explore

| File | What you'll see |
|------|----------------|
| `START_HERE.md` | Dynamic entry point with actionable state |
| `HEALTH_HOME.md` | Visual home screen with status bar and pattern signals |
| `TODAY.md` | Today's priorities with checkbox actions |
| `HEALTH_TRENDS.md` | LDL trending down with sparklines and arrows |
| `WEIGHT_TRENDS.md` | Weight series with visual sparkline |
| `NEXT_APPOINTMENT.md` | Cardiology visit prep with portal message draft |
| `REVIEW_WORKLIST.md` | Conversational review queue |
| `inbox/` | A sample referral letter ready to process |

## Try it

```bash
# Process the inbox file
python3 scripts/care_workspace.py process-inbox --root examples/demo-karen

# Generate a focused dashboard
python3 scripts/care_workspace.py query-dashboard --root examples/demo-karen \
  --query "how is Karen's cholesterol doing?" --save

# View extraction accuracy
python3 scripts/care_workspace.py extraction-audit --root examples/demo-karen
```

## The story

Karen was diagnosed with high cholesterol in September 2025 (LDL 188). She started atorvastatin 10mg, which was later increased to 20mg. Over 6 months her LDL dropped to 141 — improving but still above the <100 goal. Her PCP referred her to a cardiologist to discuss whether to increase the dose or add combination therapy. She also has well-controlled hypertension on lisinopril and a borderline Vitamin D level.

Her next appointment is with Dr. Park on May 8, 2026.
