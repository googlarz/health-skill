# Health Skill

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Local-first health organization and care-navigation skill for Claude.

Health Skill turns normal folders into durable health workspaces. It helps Claude organize records, explain labs in context, prepare for appointments, track follow-ups, and keep structured memory across sessions — without a cloud platform.

## Why This Exists

Most health-related AI use loses context between sessions. You upload a PDF, ask a few questions, and everything disappears into chat history.

Health Skill solves that by giving Claude a durable workspace. Future sessions start from current conditions, medications, recent labs, pending follow-ups, and unresolved questions. A single lab result is useful; a lab result connected to past results, medication changes, and follow-up plans is much more useful.

## Quick Start

```bash
# Initialize a person folder
python3 scripts/care_workspace.py init-project --root . --name "Jane Doe"

# Drop files into inbox/ then process them
python3 scripts/care_workspace.py process-inbox --root .

# Preview what inbox processing would do
python3 scripts/care_workspace.py process-inbox --root . --dry-run
```

Then open `HEALTH_HOME.md`, `TODAY.md`, or `NEXT_APPOINTMENT.md`.

## Key Files

| File | Purpose |
|------|---------|
| `HEALTH_HOME.md` | All-in-one home screen |
| `TODAY.md` | What to do now |
| `NEXT_APPOINTMENT.md` | Visit prep |
| `HEALTH_PROFILE.json` | Structured source of truth |

See [docs/files.md](docs/files.md) for the full list.

## Who This Is For

- People managing recurring appointments, labs, and meds
- Caregivers helping a parent, partner, or child
- Anyone who wants Claude to be useful across months, not just one conversation

## What It Does Well

- Durable health folder per person
- Lab and medication tracking with trends
- Trust-aware extraction (facts labeled by confidence)
- Appointment prep and clinician packets
- Caregiver dashboard across multiple people
- Portable exports (ICS calendars, redacted summaries, handoff notes)

## What It Is Not

- Not a doctor or diagnostic system
- Not a prescribing tool
- Not a HIPAA-compliant SaaS product
- Not a replacement for emergency care

## Safety Model

Health Skill is intentionally bounded. It explains and organizes clinician-given information, helps with visit prep and care navigation, and escalates conservatively when symptoms sound urgent. See [references/safety-protocol.md](references/safety-protocol.md).

## Review Workflow

Extracted facts are labeled by confidence:

- `safe_to_auto_apply` — high-confidence structured data
- `needs_quick_confirmation` — likely correct but worth checking
- `do_not_trust_without_human_review` — OCR or low-confidence extraction

## Project Structure

```text
health-skill/
  SKILL.md          # Runtime behavior for Claude
  README.md
  scripts/
    care_workspace.py   # Core data model and storage
    rendering.py        # View generation
    extraction.py       # Document processing and inbox
    commands.py         # CLI commands and parser
    clinician_handoff.py
    caregiver_dashboard.py
    apple_ocr.swift     # macOS Vision OCR
  references/
  assets/
  tests/
  docs/
```

## Tests

```bash
python3 -m unittest discover tests -v
```

## Documentation

- [SKILL.md](SKILL.md) — Runtime behavior and Claude instructions
- [docs/setup-guide.md](docs/setup-guide.md) — Detailed setup for non-technical users
- [docs/commands.md](docs/commands.md) — CLI command reference
- [docs/files.md](docs/files.md) — Workspace files reference
- [references/cowork-tutorial.md](references/cowork-tutorial.md) — Human workflow guide
- [CONTRIBUTING.md](CONTRIBUTING.md) — How to contribute

## License

[MIT](LICENSE)
