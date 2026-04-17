<p align="center">
  <h1 align="center">Health Skill</h1>
  <p align="center">
    Local-first health workspace for Claude — organize records, track labs, prepare for visits, keep memory across sessions.
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/tests-110%20passing-brightgreen" alt="Tests">
    <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  </p>
</p>

---

> One person = one folder. The folder is the memory, not the chat.

Health Skill gives Claude a **durable workspace** so it can reason across your full health picture — labs connected to medications connected to follow-ups — instead of starting from scratch every conversation.

## See It In Action

Explore the [demo workspace](examples/demo-karen/) for Karen Mitchell — a realistic example with lab trends, weight tracking, medications, and visit prep.

```
# Karen's HEALTH_HOME.md

⚠️ 1 file(s) in inbox | ✅ No items need review | ✅ No overdue follow-ups
────────────────────────────────────────

## Right Now
- Process 1 file(s) sitting in inbox.
- Keep an eye on abnormal labs: LDL 141 mg/dL, Vitamin D 28 ng/mL

## LDL Trend
- Trend: 188 → 162 → 141 ↓ (notable improvement on atorvastatin)

## Weight
- Latest: 76.1 kg | Trend: █▅▃▁ (-2.7%)
```

## Quick Start

### With Claude Cowork (recommended)

1. Create a folder for each person (e.g., `~/Health/mom/`)
2. Open it in Claude Cowork → `Use existing folder`
3. Tell Claude: `Use /health-skill` and `Initialize this folder for Mom`
4. Drop health documents into `inbox/` and ask Claude to process them

### From the command line

```bash
# Initialize
python3 scripts/care_workspace.py init-project \
  --root ~/Health/mom --name "Mom"

# Drop a lab report into inbox/, then process
python3 scripts/care_workspace.py process-inbox --root ~/Health/mom

# Ask a question — get a focused dashboard
python3 scripts/care_workspace.py query-dashboard \
  --root ~/Health/mom --query "how are Mom's labs?" --save
```

## What You Get

| File | What it does |
|------|-------------|
| **`HEALTH_HOME.md`** | Visual home screen — status bar, priorities, patterns, progress |
| **`TODAY.md`** | Smallest useful set of actions with ☐ checkboxes |
| **`NEXT_APPOINTMENT.md`** | Visit prep — 30-second summary, portal message draft, questions |
| **`HEALTH_TRENDS.md`** | Lab trends with sparklines and directional arrows |
| **`WEIGHT_TRENDS.md`** | Weight series with visual sparkline chart |
| `START_HERE.md` | Dynamic entry point — shows what changed since last session |
| `HEALTH_DOSSIER.md` | Comprehensive context for Claude to read first |
| `REVIEW_WORKLIST.md` | Conversational review: "Items I'm Confident About" / "Items That Need Your Eye" |

See [docs/files.md](docs/files.md) for the complete list.

## Key Features

**Query-relevant dashboards** — Ask any health question and get a focused view with only the relevant data, not the full dossier.

**Trust-aware extraction** — Facts are labeled by confidence. OCR-derived data is flagged for review. You confirm what matters.

**Medication safety** — Adding a medication that conflicts with a known allergy triggers a warning automatically.

**Pattern detection** — Connects labs to medications to follow-ups over time. Flags stale tests, temporal side-effect correlations, and overdue follow-ups.

**Extraction accuracy audit** — Tracks what was extracted vs. what you accepted/rejected, so you know which patterns are working.

**Caregiver dashboard** — One view across multiple person folders with urgency scoring and follow-up reminders.

## Who This Is For

- Managing your own recurring appointments, labs, and medications
- Helping a parent, partner, or child with health admin
- Keeping Claude useful across months, not just one conversation
- Anyone who cares more about continuity and organization than flashy app UX

## What It Is Not

- Not a doctor, diagnostic system, or prescribing tool
- Not a HIPAA-compliant platform
- Not a replacement for emergency care or licensed clinicians

See [references/safety-protocol.md](references/safety-protocol.md) for the full safety model.

## Project Structure

```
health-skill/
  SKILL.md                    # Claude runtime behavior
  scripts/
    care_workspace.py         # Core data model (1200 lines)
    rendering.py              # Visual view generation (2500 lines)
    extraction.py             # Document processing + inbox (900 lines)
    commands.py               # CLI (1400 lines)
    clinician_handoff.py      # Visit-specific handoffs
    caregiver_dashboard.py    # Multi-person overview
    apple_ocr.swift           # macOS Vision OCR
  tests/                      # 110 tests
  docs/                       # Setup guide, commands, file reference
  examples/demo-karen/        # Pre-populated demo workspace
  references/                 # Safety protocol, integration points
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [SKILL.md](SKILL.md) | How Claude uses the skill at runtime |
| [docs/setup-guide.md](docs/setup-guide.md) | Step-by-step for non-technical users |
| [docs/commands.md](docs/commands.md) | Full CLI reference |
| [docs/files.md](docs/files.md) | Every workspace file explained |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Tests

```bash
python3 -m unittest discover tests -v   # 110 tests, ~1.5s
```

## License

[MIT](LICENSE)
