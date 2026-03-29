# Health Skill

Local-first health organization and care-navigation skill for Claude Cowork.

Health Skill turns normal folders into durable health workspaces for one person or an entire family. It helps Claude organize records, explain labs in context, prepare for appointments, track follow-ups, and keep a structured memory across sessions without depending on a cloud health platform.

It is built for people who want something practical:

- a folder they control
- continuity across Claude sessions
- better appointment prep
- safer document organization
- less repeating the same health story over and over

## At A Glance

- One person = one folder
- Claude reads the folder, not just the chat history
- New files go into `inbox/` and move to `Archive/` after processing
- The workspace keeps summaries, review queues, trends, and visit prep up to date
- Best used in Claude Cowork with `Use existing folder`

## Why This Exists

Most health-related AI use falls apart in the real world for one simple reason: continuity.

You upload a PDF, ask a few questions, get an answer, and then everything important disappears into chat history.

Health Skill is meant to solve that. It gives Claude a durable workspace so future sessions can start from:

- current conditions
- current medications
- recent labs
- pending follow-ups
- unresolved questions
- caregiver context

That makes it much more useful for real family health management than a one-off “health chat.”

## Why I Built It

I am building Health Skill for real family use, not as a demo.

I wanted something more durable than ad hoc chats, scattered PDFs, and vague memory. I wanted a system where Claude could come back to the same folder weeks later and still understand the person, the recent labs, the current meds, the next appointment, and the unresolved questions.

That is why this project is local-first, file-based, and opinionated about continuity.

It is designed for people like me who want:

- one folder per person
- a calm health home screen
- better appointment preparation
- a caregiver-friendly workflow
- less chaos around family health admin

## Why It Feels Different

Most health AI tools are chat-first and memory-light. Health Skill is folder-first and continuity-first.

That means:

- your health context lives in files you can inspect
- Claude can resume from the workspace state
- new documents improve future sessions
- review, trust, conflicts, and follow-ups stay visible

For the right user, that is often more useful than a generic “AI doctor” chat.

## What It Is

This project is a local skill plus a workspace toolkit.

- One person = one folder
- New files go into `inbox/`
- Processed files move into `Archive/`
- Claude keeps a structured record plus human-friendly views up to date
- The folder becomes the long-term memory, not the chat thread

This is designed for Claude Cowork and the "Use existing folder" workflow.

## What You Get

Health Skill gives you both a workflow and a set of outputs that stay useful over time:

- `HEALTH_HOME.md` for the calm all-in-one overview
- `TODAY.md` for the smallest useful next actions
- `NEXT_APPOINTMENT.md` for visit prep
- `REVIEW_WORKLIST.md` for trust-aware extracted facts
- `HEALTH_PROFILE.json` for structured continuity
- `HEALTH_TIMELINE.md` and trend files for longer-term context

## Who This Is For

Health Skill is especially useful if you:

- manage your own recurring appointments, labs, and meds
- help a parent, partner, or child with health admin
- want one folder per person instead of scattered notes and chat history
- want Claude to be useful across months, not just one conversation
- care more about organization and continuity than about flashy app UX

## A Real Project Instruction Example

One of the best ways to use Health Skill is to layer project-specific rules on top of it.

For example, this is the kind of Claude project instruction that can sit above the skill in a real family workspace:

```md
Use /health-skill

## Project Context

This is a family health management workspace. There are multiple person folders under `Health/`.

Examples:
- `Health/Person-A/`
- `Health/Person-B/`
- `Health/Person-C/`
- `Health/Person-D/`

Each person folder contains:
- HEALTH_PROFILE.md — structured health summary
- Lab result summaries (dated markdown files)
- Originals/ — source documents
- Clinic briefs and special reports as needed

## Default Behaviors

1. Always ask which person the request is about before starting any health task, unless the message makes it obvious.
2. Read HEALTH_PROFILE.md first before answering any health question about a person — it is the source of truth for current conditions, medications, and allergies.
3. Follow the health-skill protocol for all health-related tasks: triage, lab explanation, visit prep, medication review, document ingestion.
4. Save outputs to the correct person folder — never mix files between people.
5. Use the family or clinician-facing language expected in the workspace. Use English for internal workspace files unless asked otherwise.
6. Emergency rule is absolute — if any message contains urgent symptoms, lead with the escalation recommendation before anything else.

## Workspace Maintenance

- When new lab results or documents are added to a person's folder, process them and update HEALTH_PROFILE.md.
- Keep lab summaries dated (YYYY-MM-DD format).
- For cross-person comparisons or caregiver overview, reference the `Health/` root level.
- Archive original source documents in each person's Originals/ folder.

## What This Project Is NOT For

- Diagnosis or prescribing
- Emergency dispatch (call 112/999/911 instead)
- Replacing clinician judgment
```

That is a good example of the intended model:

- the skill gives you a strong reusable health workflow
- the project instruction adds workspace-specific rules
- the folders provide continuity across time

If your workspace already uses conventions like `HEALTH_PROFILE.md` or `Originals/`, that is fine. The skill works best when the project instruction clearly declares those conventions so Claude follows them consistently.

## 5-Minute Setup For Non-Technical Users

If you are not technical, use this path.

### 1. Download the project

- Download the repository from GitHub using `Code` -> `Download ZIP`
- Unzip it somewhere easy to find, like your Desktop or Documents folder.

### 2. Create a folder for one person

Example:

```text
Jane Doe Health/
```

This will be the long-term folder for that person.

### 3. Open Claude Cowork

- Start a new project
- Choose `Use existing folder`
- Pick the person folder you just made

### 4. Put the skill folder somewhere stable

Keep the unzipped `health-skill` folder somewhere you will not move around often, because the helper commands reference that location.

Example:

```text
Documents/health-skill/
```

### 5. Initialize the person folder

If you are comfortable with Terminal, run:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py init-project --root . --name "Jane Doe"
```

If you are not comfortable with Terminal, the easiest practical option is:

- open Terminal
- drag the `care_workspace.py` file into the Terminal window
- type a space, then:

```text
init-project --root . --name "Jane Doe"
```

- press Enter from inside the person folder

### 6. Start using it

- drop new health files into `inbox/`
- ask Claude to help you review the folder
- use `HEALTH_HOME.md`, `TODAY.md`, and `NEXT_APPOINTMENT.md` first

## Installation Notes

This repository is easiest to use in one of two ways:

### Option A: Use it as a local project toolkit

This is the simplest path and the one most people should use.

- keep the `health-skill` folder on your machine
- use its scripts to initialize and maintain person folders
- open each person folder in Claude Cowork with `Use existing folder`

### Option B: Install it as a local skill folder

If your Claude setup supports local skills, place the whole `health-skill/` folder in your local skills directory.

The exact skills folder location depends on your local Claude/Codex setup, so this README does not hard-code a path that may be wrong for your environment.

## What It Is Good At

- Keeping one durable health folder per person
- Explaining labs and trends in context
- Tracking medications, allergies, follow-ups, and questions
- Preparing for PCP, specialist, urgent care, or telehealth visits
- Managing review queues when extracted facts are uncertain
- Supporting caregivers across multiple person folders
- Producing portable exports like clinician packets, portal drafts, redacted summaries, and calendar files

## What It Is Not

- Not a doctor
- Not a diagnostic system
- Not a prescribing tool
- Not a HIPAA-compliant SaaS product
- Not a replacement for emergency care or licensed clinicians

This repository is best understood as a strong local health workspace for Claude, not a regulated healthcare platform.

## Core Idea

Most AI health tools lose context between sessions or hide the record inside a proprietary app.

Health Skill takes the opposite approach:

- your files stay in your folder
- the record is inspectable
- the structured data is editable
- Claude can resume work from the folder state
- each new document makes future sessions better

## Main Files

After initialization, a person folder can contain:

- `HEALTH_HOME.md`: calm all-in-one home screen
- `HEALTH_DOSSIER.md`: comprehensive canonical context
- `HEALTH_SUMMARY.md`: quick snapshot
- `TODAY.md`: what matters now
- `THIS_WEEK.md`: planning view
- `NEXT_APPOINTMENT.md`: visit prep
- `REVIEW_WORKLIST.md`: review queue grouped by trust tier
- `CARE_STATUS.md`: visible progress board
- `INTAKE_SUMMARY.md`: plain-language report after inbox processing
- `ASSISTANT_UPDATE.md`: last conversational workspace action
- `HEALTH_PROFILE.json`: structured source of truth
- `HEALTH_CONFLICTS.json`: source disagreements
- `HEALTH_REVIEW_QUEUE.json`: extracted facts needing confirmation
- `HEALTH_TRENDS.md`: lab trends
- `WEIGHT_TRENDS.md`: weight trends
- `VITALS_TRENDS.md`: non-weight vitals like blood pressure or glucose
- `HEALTH_TIMELINE.md`: unified timeline
- `HEALTH_CHANGE_REPORT.md`: recent changes
- `health_metrics.db`: local SQLite metrics store

## Key Features

### 1. Inbox-first document workflow

Drop files into `inbox/`, run `process-inbox`, and Health Skill will:

- ingest the file
- extract likely facts
- move the original into `Archive/`
- refresh the workspace views
- create a review queue when confidence is limited

### 2. Human-friendly views

The workspace is not just raw JSON. It generates readable files designed for real use when someone is tired, stressed, or short on time.

### 3. Trust-aware extraction

Facts are labeled by source and confidence:

- confirmed from source document
- accepted after review
- user-reported
- document-derived and should be reviewed

### 4. Appointment prep

Health Skill generates:

- visit briefs
- clinician packets
- appointment request drafts
- portal message drafts
- focused questions based on recent changes

### 5. Longitudinal tracking

Track not just documents and notes, but also:

- weight
- blood pressure
- glucose
- heart rate
- oxygen saturation
- sleep hours
- pain or mood scores
- adherence or symptom scores

### 6. Caregiver coordination

Across multiple person folders, Health Skill can generate:

- caregiver dashboard
- weekly summary
- caregiver handoff

## Folder Workflow

### Step 1: Create or choose a folder

Example:

```text
jane-doe-health/
```

### Step 2: Open it in Claude Cowork

Start a new project and choose `Use existing folder`.

### Step 3: Initialize the folder

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py init-project \
  --root . \
  --name "Jane Doe" \
  --date-of-birth 1980-01-01 \
  --sex female
```

### Step 4: Start using it

- drop new records into `inbox/`
- process the inbox
- review uncertain extracted facts
- use `HEALTH_HOME.md`, `TODAY.md`, and `NEXT_APPOINTMENT.md` as the main entry points

## Best First Experience

If you want to feel the value quickly, do this:

1. create one person folder
2. initialize it
3. drop one lab file into `inbox/`
4. process the inbox
5. open `HEALTH_HOME.md`
6. open `NEXT_APPOINTMENT.md`

That shows the core product loop better than reading the whole repo.

## Quick Start Commands

Initialize a person folder:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py init-project --root . --name "Jane Doe"
```

Process inbox:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py process-inbox --root .
```

Add a structured medication:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py upsert-record \
  --root . \
  --section medications \
  --value '{"name":"atorvastatin","dose":"10 mg nightly","status":"active"}'
```

Record weight:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py record-weight \
  --root . \
  --value 81.2 \
  --unit kg \
  --date 2026-03-25 \
  --note "Morning weight"
```

Record blood pressure:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py record-vital \
  --root . \
  --metric blood_pressure \
  --value "128/82" \
  --unit mmHg \
  --date 2026-03-25 \
  --note "Home cuff"
```

Generate a clinician packet:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py export-clinician-packet \
  --root . \
  --visit-type specialist \
  --reason "Follow-up for elevated LDL"
```

Generate a redacted summary:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py export-redacted-summary --root .
```

Create a backup archive:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py backup-project --root .
```

## If You Only Remember Three Files

- `HEALTH_HOME.md`: the best overall starting point
- `TODAY.md`: what to do now
- `NEXT_APPOINTMENT.md`: what to bring to the next visit

## Review Workflow

When Health Skill extracts facts from documents, it does not pretend everything is equally reliable.

Review tiers:

- `safe_to_auto_apply`
- `needs_quick_confirmation`
- `do_not_trust_without_human_review`

Useful commands:

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py list-review-queue --root .
python3 /absolute/path/to/health-skill/scripts/care_workspace.py apply-review-tier --root . --tier safe_to_auto_apply
python3 /absolute/path/to/health-skill/scripts/care_workspace.py resolve-review-tier --root . --tier do_not_trust_without_human_review --status rejected --note "Needs manual confirmation"
```

## Caregiver Workflow

If you keep multiple person folders under one parent directory:

```text
family-health/
  jane-doe-health/
  john-doe-health/
  parent-health/
```

You can generate:

```bash
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py --root /absolute/path/to/family-health
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py --root /absolute/path/to/family-health --weekly-summary
python3 /absolute/path/to/health-skill/scripts/caregiver_dashboard.py --root /absolute/path/to/family-health --handoff
```

## Safety Model

Health Skill is intentionally bounded.

- It helps explain and organize clinician-given information.
- It can help with visit prep and care navigation.
- It should escalate conservatively when symptoms sound urgent.
- It should not diagnose or prescribe.

If the user reports a medical emergency, the correct action is emergency care, not more workflow automation.

## Local-First "Production Ready"

For a local Claude skill, this project is in strong shape:

- stable folder model
- tested CLI workflows
- durable structured record
- useful user-facing outputs
- local backup support
- privacy-aware shareable exports

For a commercial or regulated healthcare product, it is not production-ready yet. It does not claim HIPAA compliance, formal security certification, clinical validation, or direct EHR-grade integration.

For the intended use case, though, this *is* the production version:

- local
- file-based
- practical
- durable
- ready to use in real Claude Cowork projects

## Verification

The current test suite passes with:

```bash
python3 -m unittest tests.test_care_workspace
```

Recent coverage includes:

- project initialization
- inbox processing and archival
- review queue behavior
- trend generation
- caregiver dashboard and handoff
- vitals tracking
- appointment prep outputs
- redacted exports
- backup archive creation

## Repository Structure

```text
health-skill/
  SKILL.md
  README.md
  scripts/
  references/
  assets/
  tests/
```

## Best Starting Point

If you only read one thing after cloning the repo, read:

- [SKILL.md](./SKILL.md) for the runtime behavior
- [references/cowork-tutorial.md](./references/cowork-tutorial.md) for the human workflow

## License / Usage

This repository is released under the [MIT License](./LICENSE).
