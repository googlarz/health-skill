# Health Skill v2.2 Release Plan

Shipping all v2.2 / v2.3 / v2.4 roadmap features as a single release.

## Feature inventory

| # | Feature | Roadmap origin | New file | Impact |
|---|---------|---------------|----------|--------|
| 1 | Drug-drug + supplement-drug interaction checker | v2.3 | `interactions.py` | Safety-critical |
| 2 | Personalised lab reference ranges | v2.3 | `lab_ranges.py` | Clinical depth |
| 3 | Medication side-effect timeline | v2.2 | `side_effects.py` | Smarter connections |
| 4 | Monthly insight report | v2.2 | `monthly_report.py` | Ambient |
| 5 | FHIR / CCD import | v2.3 | `fhir_import.py` | Data ingestion |
| 6 | Mental health layer | v2.4 | `mental_health.py` | Daily companion |
| 7 | Symptom differential tracking | v2.4 | extends `triage.py` | Clinical depth |
| 8 | Continuous pattern alerts incl. non-dipping BP | v2.4 | extends `nudges.py` | Ambient |
| 9 | Running metrics tracker | new | extends `training.py` | Athletic depth |
| 10 | Intervention tracker | new | extends `care_workspace.py` | BP / rehab tracking |
| 11 | Silent auto-save behavior | new | `SKILL.md` rule | Core UX |

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
- `interactions.py`: drug-drug **and supplement-drug** interaction database + checker
  - Supplement pairs to cover at minimum: natto+ARB (potassium), beetroot+antihypertensives (BP stacking), fish oil+anticoagulants, vitamin K2+warfarin, hibiscus+BP meds
  - Supplements stored in profile under `supplements[]` alongside medications
- CLI: `check-interactions`, `lab-ranges`
- Tests: interaction detection, supplement-drug pairs, range personalisation
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
- **Add non-dipping BP alert**: if nocturnal BP average < 10% below daytime average across ≥3 paired readings → flag "non-dipping pattern detected — mention to GP"
- No new CLI — integrated into existing `nudges` command
- Tests: alert triggers at correct thresholds, non-dipping detection
- Verify: `python3 -m pytest tests/test_v22.py::PatternAlertTests`

### Slice 9 — Running metrics tracker (extend training.py)
- Extend workout schema to store advanced run fields: TSS, NGP, power_avg_w, power_np_w, gct_ms, vertical_osc_cm, epoc, pte, cadence_avg, cadence_max, stride_length_cm, recovery_hr_drop, vo2max_est, recovery_time_h, temp_c, zone_breakdown (dict)
- `run_summary(root, person_id, n=5)` — last N runs with trend deltas (pace, HR, TSS, VO2max est.)
- CLI: `run-summary`
- Tests: schema round-trip, summary with 0/1/5 runs
- Verify: `python3 -m pytest tests/test_v22.py::RunMetricsTests`

### Slice 10 — Intervention tracker (extend care_workspace.py)
- `log_intervention(root, person_id, name, start_date, protocol, outcome_metric)` — track named interventions (e.g. "wall-sit-BP", "chin-tuck-posture") with start date and what to measure
- `intervention_status(root, person_id)` — list active interventions + days running + latest outcome value
- Interventions stored in `HEALTH_PROFILE.json` under `interventions[]`
- CLI: `intervention-log`, `intervention-status`
- Tests: log, status, missing outcome metric
- Verify: `python3 -m pytest tests/test_v22.py::InterventionTests`

### Checkpoint — Full suite green
- `python3 -m pytest tests/ -q` — all passing
- `python3 -m mypy scripts/ --ignore-missing-imports` — no new errors

### Slice 8 — Wire + docs
- `commands.py`: add all new subcommands (incl. `run-summary`, `intervention-log`, `intervention-status`)
- `SKILL.md`: document new behaviors incl. silent auto-save rule
- `README.md`: update version badge, add v2.2 section
- Verify: `python3 -m pytest tests/test_v22.py::CLIWiringTests`

## Success criteria

- All 11 features implemented and tested
- Full test suite passes (target: 210+ tests)
- No mypy regressions
- README updated to v2.2
- Committed and pushed
