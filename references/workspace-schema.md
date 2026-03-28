# Workspace Schema

Use this reference when editing `HEALTH_PROFILE.json` or designing automation around a person project folder.

## Core files per person

- `START_HERE.md`: orientation and reopening guide
- `HEALTH_HOME.md`: calm all-in-one home screen
- `HEALTH_PROFILE.json`: structured record with provenance-ready entries
- `HEALTH_SUMMARY.md`: human-readable overview
- `HEALTH_DOSSIER.md`: comprehensive canonical context file
- `HEALTH_CONFLICTS.json`: unresolved source conflicts
- `HEALTH_REVIEW_QUEUE.json`: extracted candidates that need confirmation or resolution
- `HEALTH_TRENDS.md`: derived lab trend view
- `WEIGHT_TRENDS.md`: derived weight trend view
- `VITALS_TRENDS.md`: non-weight metrics tracked over time
- `HEALTH_TIMELINE.md`: unified event chronology
- `HEALTH_CHANGE_REPORT.md`: recent-delta summary
- `INTAKE_SUMMARY.md`: plain-language report after inbox processing
- `ASSISTANT_UPDATE.md`: the last conversational workspace update
- `TODAY.md`: immediate next actions
- `THIS_WEEK.md`: planning surface for the next 7 days
- `NEXT_APPOINTMENT.md`: visit prep brief with questions
- `REVIEW_WORKLIST.md`: user-friendly review queue grouped by trust tier
- `CARE_STATUS.md`: visible progress / completion board
- `inbox/`: unprocessed source files
- `Archive/`: processed originals after ingestion
- `notes/`: dated event notes
- `exports/`: generated clinician handoffs and similar outputs
- `health_metrics.db`: local SQLite database for weight entries

## `HEALTH_PROFILE.json` top-level fields

- `schema_version`
- `person_id`
- `name`
- `date_of_birth`
- `sex`
- `conditions`
- `medications`
- `allergies`
- `clinicians`
- `recent_tests`
- `care_goals`
- `follow_up`
- `unresolved_questions`
- `documents`
- `encounters`
- `preferences`
- `consents`
- `audit`

## `health_metrics.db`

Tables:

- `weight_entries`
- `vital_entries`

Recommended vital metrics:

- `blood_pressure`
- `glucose`
- `heart_rate`
- `oxygen_saturation`
- `sleep_hours`
- `symptom_score`
- `adherence`
- `pain_score`
- `mood_score`
- `weight`

## `HEALTH_PROFILE.json.preferences`

Recommended keys:

- `summary_style`
- `weight_unit`
- `primary_caregiver`
- `appointment_prep_style`
- `communication_tone`
- `preferred_clinicians`

## Review queue items

Each review queue item should include:

- `id`
- `status`
- `applied`
- `section`
- `candidate`
- `confidence`
- `rationale`
- `source_title`
- `source_date`
- `detected_at`

Recommended review tiers:

- `safe_to_auto_apply`
- `needs_quick_confirmation`
- `do_not_trust_without_human_review`

The markdown worklist should translate these into plain-language labels so the user can act without reading raw JSON.

## Record conventions

Most list entries should include:

- a primary identifier such as `name`, `substance`, `task`, or `title`
- `source`
- `last_updated`

The `source` object should contain:

- `type`
- `label`
- `date`

Wherever possible, the user-facing markdown files should render this provenance as a plain-language trust label such as:

- confirmed from source document
- accepted after review
- user-reported
- document-derived and should be reviewed

## Conflict handling

When a later source changes a non-empty field on an existing record, the workspace should:

1. keep the latest value in `HEALTH_PROFILE.json`
2. append a review item to `HEALTH_CONFLICTS.json`
3. surface the open conflict in `HEALTH_SUMMARY.md`
4. surface the same conflict in `HEALTH_DOSSIER.md`

This keeps the current view useful while preserving review visibility.
