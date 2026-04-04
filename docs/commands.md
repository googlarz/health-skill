# CLI Commands Reference

## Quick Start

```bash
# Initialize a person folder
python3 scripts/care_workspace.py init-project --root . --name "Jane Doe"

# Process inbox
python3 scripts/care_workspace.py process-inbox --root .

# Preview inbox processing without moving files
python3 scripts/care_workspace.py process-inbox --root . --dry-run
```

## Record Management

```bash
# Add a medication
python3 scripts/care_workspace.py upsert-record \
  --root . --section medications \
  --value '{"name":"atorvastatin","dose":"10 mg nightly","status":"active"}'

# Record weight
python3 scripts/care_workspace.py record-weight \
  --root . --value 81.2 --unit kg --date 2026-03-25 --note "Morning weight"

# Record blood pressure
python3 scripts/care_workspace.py record-vital \
  --root . --metric blood_pressure --value "128/82" --unit mmHg --date 2026-03-25
```

## Review Queue

```bash
# List review items
python3 scripts/care_workspace.py list-review-queue --root .

# Auto-apply safe items
python3 scripts/care_workspace.py apply-review-tier --root . --tier safe_to_auto_apply

# Reject untrusted items
python3 scripts/care_workspace.py resolve-review-tier --root . \
  --tier do_not_trust_without_human_review --status rejected --note "Needs manual check"
```

## Exports

```bash
# Clinician packet
python3 scripts/care_workspace.py export-clinician-packet \
  --root . --visit-type specialist --reason "Follow-up for elevated LDL"

# Redacted summary
python3 scripts/care_workspace.py export-redacted-summary --root .

# Backup archive
python3 scripts/care_workspace.py backup-project --root .
```

## Caregiver Dashboard

```bash
python3 scripts/caregiver_dashboard.py --root /path/to/family-health
python3 scripts/caregiver_dashboard.py --root /path/to/family-health --weekly-summary
python3 scripts/caregiver_dashboard.py --root /path/to/family-health --handoff
```

## Clinician Handoff

```bash
python3 scripts/clinician_handoff.py --root . --reason "Cardiology consult" --visit-type specialist
```
