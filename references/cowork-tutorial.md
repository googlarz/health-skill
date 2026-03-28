# Project Folder Tutorial

Use this when the user wants one person per Claude Cowork project folder.

## Why this layout

The folder itself is the working memory for that person. The user can start a new Claude project, choose `Use existing folder`, and point it at the person's health folder.

That folder should contain:

- new source files waiting in `inbox/`
- processed originals in `Archive/`
- notes Claude writes over time
- a structured health profile
- a comprehensive dossier Claude can read first in future sessions

## Recommended layout

```text
jane-doe-health/
  START_HERE.md
  HEALTH_HOME.md
  HEALTH_DOSSIER.md
  HEALTH_SUMMARY.md
  HEALTH_PROFILE.json
  HEALTH_CONFLICTS.json
  HEALTH_REVIEW_QUEUE.json
  HEALTH_TRENDS.md
  WEIGHT_TRENDS.md
  VITALS_TRENDS.md
  HEALTH_TIMELINE.md
  HEALTH_CHANGE_REPORT.md
  INTAKE_SUMMARY.md
  ASSISTANT_UPDATE.md
  TODAY.md
  THIS_WEEK.md
  NEXT_APPOINTMENT.md
  REVIEW_WORKLIST.md
  CARE_STATUS.md
  inbox/
    2026-03-20-lipid-panel.pdf
  Archive/
  notes/
    2026-03-25-intake.md
    2026-03-27-pcp-follow-up.md
  exports/
    clinician_handoff_specialist.md
```

## File roles

- `HEALTH_DOSSIER.md`: comprehensive canonical context file Claude should read first
- `HEALTH_SUMMARY.md`: shorter quick-look snapshot
- `HEALTH_HOME.md`: calm all-in-one home screen
- `HEALTH_PROFILE.json`: structured source of truth for stable facts
- `START_HERE.md`: orientation file for humans or Claude when reopening the project
- `HEALTH_CONFLICTS.json`: facts that disagree across sources and need review
- `HEALTH_REVIEW_QUEUE.json`: extracted candidates that need confirmation or resolution
- `HEALTH_TRENDS.md`: derived lab trends over time
- `WEIGHT_TRENDS.md`: derived weight trends from the local metrics database
- `VITALS_TRENDS.md`: non-weight vitals tracked over time
- `HEALTH_TIMELINE.md`: unified chronology across encounters, notes, meds, follow-ups, and weights
- `HEALTH_CHANGE_REPORT.md`: recent change summary, defaulting to the last 30 days
- `INTAKE_SUMMARY.md`: plain-language summary after inbox processing
- `ASSISTANT_UPDATE.md`: last workspace action in conversational language
- `TODAY.md`: smallest set of useful actions right now
- `THIS_WEEK.md`: planning view for the coming week
- `NEXT_APPOINTMENT.md`: ready-to-use visit brief and questions
- `REVIEW_WORKLIST.md`: friendly review queue grouped by trust tier
- `CARE_STATUS.md`: progress board that makes completion visible
- `inbox/`: new files Claude has not processed yet
- `Archive/`: processed originals after ingestion
- `notes/`: dated event notes and document review notes
- `exports/`: generated handoffs and other shareable artifacts

## Setup

Inside the person folder:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py init-project \
  --root . \
  --name "Jane Doe" \
  --date-of-birth 1980-01-01 \
  --sex female
```

This creates the structured files and an initial dossier without touching existing files outside the project folder.

## Daily operating pattern

When Claude works in this folder:

1. Read `HEALTH_HOME.md` or `HEALTH_DOSSIER.md` first.
2. Check `TODAY.md` or `NEXT_APPOINTMENT.md` if the user needs a quick actionable view.
3. Check `HEALTH_SUMMARY.md` for the latest quick record snapshot.
4. Check `REVIEW_WORKLIST.md` if inbox extraction happened recently.
5. Open only the relevant notes or documents for the current task.
6. Answer the user.
7. If new stable facts were provided, update `HEALTH_PROFILE.json`.
8. If a source file was added, place it in `inbox/` and process the inbox.
9. Refresh the dossier and the user-facing views.
10. Add weight entries when the user shares them, so long-term change becomes visible.
11. Use the timeline and change report when the user asks what changed recently.

## Common commands

Update a scalar field:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py update-profile \
  --root . \
  --field date_of_birth \
  --value '"1980-01-01"'
```

Upsert structured data:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py upsert-record \
  --root . \
  --section medications \
  --value '{"name":"atorvastatin","dose":"10 mg nightly","status":"active"}' \
  --source-type user \
  --source-label "patient message"
```

Process files from `inbox/` into the structured record and move them to `Archive/`:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py process-inbox \
  --root .
```

Directly ingest one file and archive it:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py ingest-document \
  --root . \
  --path ./inbox/lipid-panel.txt \
  --doc-type lab \
  --title "Outside lipid panel" \
  --source-date 2026-03-20
```

Refresh the canonical files:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-home --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-summary --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-dossier --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-today --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-this-week --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-next-appointment --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-review-worklist --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-care-status --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-intake-summary --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-trends --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-weight-trends --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-vitals-trends --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-timeline --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py render-change-report --root . --days 30
```

Create a specialist handoff:

```bash
python3 /absolute/path/to/health-skill/scripts/clinician_handoff.py \
  --root . \
  --visit-type specialist \
  --reason "Cardiology consult for elevated LDL"
```

Show review queue items:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py list-review-queue --root .
```

Apply all safe review items in one batch:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py apply-review-tier \
  --root . \
  --tier safe_to_auto_apply
```

Reject all low-trust OCR-style review items in one batch:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py resolve-review-tier \
  --root . \
  --tier do_not_trust_without_human_review \
  --status rejected \
  --note "Needs manual confirmation"
```

Set a user or caregiver preference:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py set-preference \
  --root . \
  --key primary_caregiver \
  --value '"Sam Doe"'
```

Export a follow-up calendar:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py export-calendar --root .
```

Record a weight entry:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py record-weight \
  --root . \
  --value 81.2 \
  --unit kg \
  --date 2026-03-25 \
  --note "Morning weight"
```

Record another health metric:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py record-vital \
  --root . \
  --metric blood_pressure \
  --value "128/82" \
  --unit mmHg \
  --date 2026-03-25 \
  --note "Home cuff"
```

Generate an appointment request for a provider portal or booking form:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py generate-appointment-request \
  --root . \
  --specialty cardiology \
  --reason "Follow-up for elevated LDL and medication review"
```

Create a minimal clinician packet:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py export-clinician-packet \
  --root . \
  --visit-type specialist \
  --reason "Follow-up for elevated LDL and medication review"
```

Create a redacted summary for sharing:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py export-redacted-summary --root .
```

Create a backup zip:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py backup-project --root .
```

## What Claude should optimize for

- keep `HEALTH_PROFILE.json` structured and minimal
- use `HEALTH_HOME.md` as the first-stop home screen
- keep `HEALTH_DOSSIER.md` comprehensive and current
- make `TODAY.md`, `THIS_WEEK.md`, and `NEXT_APPOINTMENT.md` the first stop for stressed or busy users
- use `inbox/` as the entry point for raw files
- move processed originals into `Archive/`
- check `REVIEW_WORKLIST.md` after inbox processing
- use `HEALTH_TRENDS.md` for repeat labs over time
- use `WEIGHT_TRENDS.md` for longitudinal weight context
- use `VITALS_TRENDS.md` for blood pressure, glucose, heart rate, and other metrics
- use `HEALTH_TIMELINE.md` when sequencing matters
- use `HEALTH_CHANGE_REPORT.md` when the user asks what changed recently
- use `CARE_STATUS.md` to make progress visible
- keep `ASSISTANT_UPDATE.md` readable and reassuring after meaningful actions
- preserve provenance on facts
- surface source conflicts instead of pretending they do not exist
- use notes for dated context, not as the main source of truth

## Multi-person fallback

If the user truly wants one repo for many people, the older `care-workspace/people/<person_id>/...` layout still works.

That is now secondary. The preferred flow is one person folder per Claude project.

If a caregiver keeps multiple person project folders under one parent folder, build a shared dashboard:

```bash
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py \
  --root /absolute/path/to/family-health
```

For a weekly cross-person review:

```bash
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py \
  --root /absolute/path/to/family-health \
  --weekly-summary
```

For a caregiver handoff:

```bash
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py \
  --root /absolute/path/to/family-health \
  --handoff
```
