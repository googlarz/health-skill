# Workspace Files Reference

After initialization, a person folder can contain:

## User-Facing Views

| File | Purpose |
|------|---------|
| `HEALTH_HOME.md` | Calm all-in-one home screen |
| `TODAY.md` | What matters right now |
| `THIS_WEEK.md` | Planning view for the next 7 days |
| `NEXT_APPOINTMENT.md` | Ready-to-use visit prep |
| `START_HERE.md` | Orientation when opening the folder |
| `CARE_STATUS.md` | Visible progress board |
| `REVIEW_WORKLIST.md` | Review queue grouped by trust tier |
| `INTAKE_SUMMARY.md` | Plain-language report after inbox processing |
| `ASSISTANT_UPDATE.md` | Last conversational workspace action |

## Structured Data

| File | Purpose |
|------|---------|
| `HEALTH_PROFILE.json` | Structured source of truth |
| `HEALTH_CONFLICTS.json` | Source disagreements |
| `HEALTH_REVIEW_QUEUE.json` | Extracted facts needing confirmation |
| `health_metrics.db` | Local SQLite metrics store |

## Reports

| File | Purpose |
|------|---------|
| `HEALTH_SUMMARY.md` | Quick snapshot |
| `HEALTH_DOSSIER.md` | Comprehensive canonical context |
| `HEALTH_TRENDS.md` | Lab trends |
| `WEIGHT_TRENDS.md` | Weight trends |
| `VITALS_TRENDS.md` | Non-weight vitals |
| `HEALTH_TIMELINE.md` | Unified timeline |
| `HEALTH_CHANGE_REPORT.md` | Recent changes |
| `HEALTH_PATTERNS.md` | Cross-record connections |

## Directories

| Directory | Purpose |
|-----------|---------|
| `inbox/` | Drop new files here |
| `Archive/` | Processed originals |
| `notes/` | Dated markdown notes |
| `exports/` | Generated outputs (packets, ICS, backups) |
