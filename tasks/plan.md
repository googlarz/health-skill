# Health Skill v2.2 Release Plan

Shipping all v2.2 / v2.3 / v2.4 roadmap features as a single release.

## Feature inventory

| # | Feature | Roadmap origin | New file | Impact |
|---|---------|---------------|----------|--------|
| 1 | Drug-drug interaction checker | v2.3 | `interactions.py` | Safety-critical |
| 2 | Personalised lab reference ranges | v2.3 | `lab_ranges.py` | Clinical depth |
| 3 | Medication side-effect timeline | v2.2 | `side_effects.py` | Smarter connections |
| 4 | Monthly insight report | v2.2 | `monthly_report.py` | Ambient |
| 5 | FHIR / CCD import | v2.3 | `fhir_import.py` | Data ingestion |
| 6 | Mental health layer | v2.4 | `mental_health.py` | Daily companion |
| 7 | Symptom differential tracking | v2.4 | extends `triage.py` | Clinical depth |
| 8 | Continuous pattern alerts | v2.4 | extends `nudges.py` | Ambient |

Plus: wire all commands in `commands.py`, tests in `tests/test_v22.py`, update README + SKILL.md.

## Dependency graph

```
lab_ranges.py          ← standalone (used by interactions, side_effects)
interactions.py        ← depends on lab_ranges (for context), care_workspace
side_effects.py        ← depends on care_workspace (checkins, medications)
monthly_report.py      ← depends on care_workspace, rendering, goals, training
fhir_import.py         ← depends on care_workspace (record_vital, record_weight, save_profile)
mental_health.py       ← depends on care_workspace (checkins, load_profile)
triage.py (extend)     ← already exists, add symptom tracking
nudges.py (extend)     ← already exists, add pattern alerts
commands.py (extend)   ← depends on all above
tests/test_v22.py      ← depends on all above
```

## Task slices (vertical — each is shippable)

### Slice 1 — Safety layer (interactions + lab ranges)
- `lab_ranges.py`: personalised reference range table (conditions × markers)
- `interactions.py`: drug-drug interaction database + checker
- CLI: `check-interactions`, `lab-ranges`
- Tests: interaction detection, range personalisation
- Verify: `python3 -m pytest tests/test_v22.py::InteractionTests`

### Slice 2 — Side-effect timeline
- `side_effects.py`: side-effect database + correlate with check-in timeline
- CLI: `side-effects`
- Tests: correlation detection, no false positives on empty data
- Verify: `python3 -m pytest tests/test_v22.py::SideEffectTests`

### Slice 3 — Monthly report
- `monthly_report.py`: aggregates 30-day window across all domains
- CLI: `monthly-report`
- Tests: renders without error on minimal profile
- Verify: `python3 -m pytest tests/test_v22.py::MonthlyReportTests`

### Slice 4 — FHIR import
- `fhir_import.py`: FHIR R4 JSON parser (conditions, meds, observations, allergies)
- Route `.json` FHIR files through `process_inbox`
- CLI: `import-fhir`
- Tests: parse conditions, labs, medications from sample FHIR bundle
- Verify: `python3 -m pytest tests/test_v22.py::FHIRTests`

### Slice 5 — Mental health layer
- `mental_health.py`: PHQ-2 / GAD-2 scoring + burnout detection from check-in trends
- CLI: `mental-health`
- Tests: scoring logic, burnout detection threshold
- Verify: `python3 -m pytest tests/test_v22.py::MentalHealthTests`

### Slice 6 — Symptom differential tracking
- Extend `triage.py`: `symptom_track()` — log recurring symptom, detect triggers
- CLI: `symptom-track`
- Tests: trigger detection, deduplication
- Verify: `python3 -m pytest tests/test_v22.py::SymptomTrackTests`

### Slice 7 — Continuous pattern alerts (extend nudges)
- Extend `nudges.py`: elevated RHR streak, chronic sleep deficit, rapid weight change
- No new CLI — integrated into existing `nudges` command
- Tests: alert triggers at correct thresholds
- Verify: `python3 -m pytest tests/test_v22.py::PatternAlertTests`

### Checkpoint — Full suite green
- `python3 -m pytest tests/ -q` — all passing
- `python3 -m mypy scripts/ --ignore-missing-imports` — no new errors

### Slice 8 — Wire + docs
- `commands.py`: add all new subcommands
- `SKILL.md`: document new behaviors
- `README.md`: update version badge, add v2.2 section
- Verify: `python3 -m pytest tests/test_v22.py::CLIWiringTests`

## Success criteria

- All 8 slices implemented and tested
- Full test suite passes (target: 190+ tests)
- No mypy regressions
- README updated to v2.2
- Committed and pushed
