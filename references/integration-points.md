# Integration Points

Use this reference when adapting Health Skill to external systems.

## Goal

Keep the core skill local-first and safe, while making it easy to connect to scheduling, telehealth, or document systems later.

## Practical integrations now

What the current local workflow can support reliably:

- calendar export via `exports/follow_up_calendar.ics`
- appointment request markdown for booking forms or provider portals
- clinician handoff markdown for messages, uploads, or copy/paste
- PDF text extraction when the PDF already contains selectable text

These are export-based integrations, not direct authenticated portal automation.

## Recommended adapter boundaries

### Appointment adapter

Purpose:

- check available appointment slots
- create a booking request
- save confirmation details into the person's folder

Minimum safe fallback if no direct adapter exists:

- generate an appointment request markdown file
- generate a clinician handoff markdown file
- let the user paste or upload them manually

Expected inputs:

- `person_id`
- requested specialty or visit type
- preferred time windows
- insurance or payment notes if relevant

Expected outputs:

- booked status
- appointment date and time
- clinician or clinic name
- location or video URL
- confirmation id

### Medication adapter

Purpose:

- normalize medication names from user-entered text
- attach pharmacy or refill metadata

Expected outputs:

- normalized medication list
- refill status if available
- pharmacy contact if available

### Document adapter

Purpose:

- ingest labs, discharge summaries, and clinician-authored plans
- save extracted summaries as dated notes

Expected outputs:

- document type
- extracted key facts
- source date
- confidence notes when extraction is incomplete

## Portal automation constraint

Generic provider portal automation is not production-safe unless the exact portal and authentication model are known.

Default policy:

- do not pretend direct booking exists
- prefer explicit exports the user can upload or paste
- only add a direct integration when the endpoint and workflow are concrete and testable

## Design rules

- Keep adapters separate from medical reasoning.
- Never let an adapter invent medical interpretation.
- Store system ids in notes or structured fields only if the user wants them persisted.
- If an integration fails, continue with local summary and handoff generation rather than blocking the entire workflow.
