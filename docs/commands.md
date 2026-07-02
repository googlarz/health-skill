# CLI Commands Reference

> **Tip:** Set `export HEALTH_ROOT=~/Health/me` in your shell profile and drop `--root .` from every command below.

All commands run via:
```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py <command> [options]
```

Or if you're inside the project directory:
```bash
python3 -m scripts.commands <command> [options]
```

---

## Conversation starters

| Command | What it does |
|---|---|
| `hi` · `hello` · `hey` | Reads your workspace, picks the one most relevant thing, opens a conversation around it |
| `status` | One-glance summary: nudge counts, last check-in, open items, quick actions |

```bash
hi
status
```

---

## Setup

```bash
# Create a new person workspace
init-project --root ~/Health/me --name "Anna"

# Run the onboarding flow
onboard --root .

# Set a preference
set-preference --root . --key summary_style --value detailed

# Create a person inside an existing root
create-person --root ~/Health --person-id dad --name "Dad"
```

---

## Daily tracking

```bash
# Check-in (also: log-checkin)
daily-checkin --root . --note "mood 7, slept 6.5h, energy 6, knee pain 3"
daily-checkin --root . --note "exhausted, barely slept, stressed"   # natural language
daily-checkin --root . --note "m8 s7.5 e7 p1"                      # shorthand

# Log a workout (also: log-workout, log-run)
workout-log --root . --type run --distance 8 --duration 42 --notes "easy pace"
workout-log --root . --type strength --duration 45 --notes "squats, deadlifts"

# Run metrics summary
run-summary --root . --n 5

# Log a meal
log-meal --root . --text "chicken 200g, rice 1 cup, broccoli"

# Log a period / cycle event
cycle-log --root . --event period_start --date 2025-06-01

# Record weight
record-weight --root . --value 78.5 --unit kg

# Record a vital sign
record-vital --root . --metric blood_pressure --value "122/78" --unit mmHg
record-vital --root . --metric resting_hr --value 58 --unit bpm
record-vital --root . --metric glucose --value 5.2 --unit mmol/L
```

---

## Documents & inbox

```bash
# Drop files into inbox/, then:
process-inbox --root .

# Ingest a single document
ingest-document --root . --file inbox/labs_june.pdf

# Audit extraction accuracy
extraction-audit --root .
```

---

## Medications & supplements

```bash
# Add a medication
upsert-record --root . --section medications \
  --value '{"name":"lisinopril","dose":"10mg","frequency":"daily"}'

# Add a supplement
upsert-record --root . --section supplements \
  --value '{"name":"nattokinase","dose":"2000 FU","frequency":"daily"}'

# Medication summary card (also: meds)
med-summary --root .

# Check drug-drug and supplement-drug interactions (also: interactions)
check-interactions --root .

# Medication side-effect timeline
side-effects --root .

# Reconcile medication list
reconcile-medications --root .
```

---

## Labs & vitals

```bash
# Explain a single lab result in plain English
explain-lab --root . --marker LDL --value 155
explain-lab --root . --marker A1C --value 6.2 --unit "%"

# Show personalised reference range (also: labs)
lab-range --root . --marker LDL --value 155
lab-range --root . --marker TSH --value 3.8

# Generate lab-to-action plan from abnormal results
lab-actions --root .

# Forecast lab markers and weight 3-6 months out
forecast --root .
```

---

## Interventions

```bash
# Log a named intervention
log-intervention --root . \
  --name "16:8 fasting" \
  --start-date 2025-01-15 \
  --protocol "Stop eating by 8pm, skip breakfast" \
  --outcome-metric weight_kg

# Check progress (also: intervention-status)
intervention-status --root .
```

---

## Appointments

```bash
# Add an upcoming appointment
add-appointment --root . --provider "Dr Smith" --date 2025-07-10 --type cardiology

# Pre-visit brief (conditions, meds, recent labs, questions to ask)
pre-visit --root . --provider "Dr Smith" --visit-type cardiology

# Process visit notes after the appointment
post-visit --root . --notes "Dr increased lisinopril to 20mg, recheck BP in 6 weeks"

# Generate appointment request letter
generate-appointment-request --root . --provider "Cardiologist" --reason "LDL elevated"
```

---

## Preventive care & screenings

```bash
# See what's overdue / due next
preventive-check --root .

# Log a completed screening
screening-log --root . --name mammogram --date 2025-05-12 --result "normal"
screening-log --root . --name colonoscopy --date 2025-03-01 --result "polyp removed"
```

---

## Goals & providers

```bash
# Add a quantified health goal
add-goal --root . --title "LDL under 130" --metric ldl --target 130 --unit mg/dL
add-goal --root . --title "Sleep 7+ hours" --metric sleep_avg --target 7

# Show goals with progress
goals --root .

# Add a care-team provider
add-provider --root . --name "Dr Anna Walsh" --role cardiologist --phone "555-1234"

# List providers
providers --root .
```

---

## Nudges, patterns & insights

```bash
# Proactive nudges (overdue items, stale labs, pattern alerts)
nudges --root .

# Weekly recap (also accepts --since 2025-05-28)
weekly-recap --root . --days 7

# Monthly 30-day insight report
monthly-report --root .

# Cross-domain pattern analysis (sleep vs pain, training vs HR, etc.)
connections --root .

# Query any health question
query-dashboard --root . --query "what should I discuss at my next appointment"
query-dashboard --root . --query "how has my sleep trended this month"
```

---

## Mental health

```bash
# PHQ-2 / GAD-2 proxy screen + burnout detection
mental-health --root .

# Structured symptom triage
triage --root . \
  --summary "Sharp chest pain when breathing" \
  --q1 "Started 2 days ago" \
  --q2 "Gets worse lying down"
```

---

## Household & family

```bash
# Add a family member
household-add-member --root ~/Health --id mom --name "Mom" --folder mom

# Add a relationship
household-add-relationship --root ~/Health --from mom --to me --type parent

# Cascade conditions as family history to all connected members
household-cascade --root ~/Health

# Household dashboard
household-dashboard --root ~/Health
```

---

## Wearables

```bash
# Import Apple Health XML or any CSV/JSON
import-wearable --root . --file inbox/export.xml
import-wearable --root . --file inbox/garmin_activities.csv

# Sync everything in inbox/wearable/
sync-wearable --root .

# Install background auto-sync watcher (macOS launchd)
setup-watch --root . --person-id me
setup-watch --root . --person-id me --status    # check status
setup-watch --root . --person-id me --uninstall
```

---

## Pharmacogenomics

```bash
# Import raw 23andMe or AncestryDNA genotype file
import-pgx --root . --file inbox/genome_raw.txt

# Generate PGX report (crosses your meds against your genotype)
pgx-report --root .
```

---

## Decision support

```bash
# Structured decision aids
decide --root . --topic hrt
decide --root . --topic statin
decide --root . --topic screening
```

---

## Exports & dashboards

```bash
# Interactive HTML dashboard (opens in browser)
dashboard --root . --open         # also: html-report

# Clinician packet for an appointment
export-clinician-packet --root . --visit-type cardiology --reason "elevated LDL"

# Portal message draft
export-portal-message --root . --topic "medication question"

# Redacted summary (safe to share)
export-redacted-summary --root .

# Calendar export (upcoming appointments as .ics)
export-calendar --root .

# Backup archive
backup-project --root .
```

---

## Review queue & conflicts

```bash
# See what needs review
list-review-queue --root .

# Apply all safe auto-extracted items
apply-review-tier --root . --tier safe_to_auto_apply

# Apply / resolve a single item
apply-review-item --root . --id <item-id>
resolve-review-item --root . --id <item-id> --status confirmed
resolve-review-item --root . --id <item-id> --status rejected --dry-run  # preview first

# List data conflicts
list-conflicts --root .

# Resolve a conflict
resolve-conflict --root . --id <conflict-id> --source "lab_report_june"
```

---

## Rendered views

One command regenerates the markdown files in your workspace. `render` with no
`--view` rebuilds every view; pass `--view <name>` for just one.

```bash
render --root .                          # regenerate every view (default)
render --root . --view today             # TODAY.md
render --root . --view this-week         # THIS_WEEK.md
render --root . --view summary           # HEALTH_SUMMARY.md
render --root . --view dossier           # HEALTH_DOSSIER.md
render --root . --view home              # HEALTH_HOME.md
render --root . --view trends            # HEALTH_TRENDS.md
render --root . --view weight-trends     # WEIGHT_TRENDS.md
render --root . --view vitals-trends     # VITALS_TRENDS.md
render --root . --view patterns          # HEALTH_PATTERNS.md
render --root . --view timeline          # HEALTH_TIMELINE.md
render --root . --view next-appointment  # NEXT_APPOINTMENT.md
render --root . --view review-worklist   # REVIEW_WORKLIST.md
render --root . --view care-status       # CARE_STATUS.md
render --root . --view intake-summary    # INTAKE_SUMMARY.md
render --root . --view change-report     # CHANGE_REPORT.md
```

---

## Aliases

These are shortcuts to the canonical commands above:

| Alias | Canonical |
|---|---|
| `hello`, `hey` | `hi` |
| `log-workout`, `log-run` | `workout-log` |
| `log-checkin` | `daily-checkin` |
| `interactions` | `check-interactions` |
| `meds` | `med-summary` |
| `labs` | `lab-range` |
| `html-report` | `dashboard` |
