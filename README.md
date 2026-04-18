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

## Contents

- [Setup for Claude Cowork](#setup-for-claude-cowork)
- [Setup for Claude Code](#setup-for-claude-code)
- [What You Get](#what-you-get)
- [Key Features](#key-features)
- [Who This Is For](#who-this-is-for)
- [What It Is Not](#what-it-is-not)
- [Documentation](#documentation)

---

## Setup for Claude Cowork

### Step 1: Install the skill

Open Claude Code (terminal) and paste:

```
Install the health-skill from https://github.com/googlarz/health-skill as a local skill
```

Claude will clone it and set it up. That's it.

Or do it manually in one line:

```bash
git clone https://github.com/googlarz/health-skill.git ~/.claude/skills/health-skill
```

### Step 2: Create a health project

1. Create a folder for each person — one person per folder:
   ```
   ~/Health/
     mom/
     dad/
     me/
   ```
2. Open Claude Cowork → **Start new project** → **Use existing folder** → pick a person folder (e.g. `~/Health/mom/`)
3. In the project instructions, add:

   ```
   Use /health-skill

   This is a health workspace for Mom.
   Always read HEALTH_DOSSIER.md before answering health questions.
   Generate a query-dashboard for every health question before responding.
   ```

4. Tell Claude: **"Initialize this folder"**

That's it. The skill is now active for every conversation in that project.

### Step 3: Start using it

- **Drop** lab PDFs, discharge notes, or visit summaries into the `inbox/` folder
- **Tell Claude**: "Process the inbox" — it extracts labs, medications, follow-ups automatically
- **Ask questions**: "What do my labs mean?", "Help me prepare for my appointment", "What's overdue?"
- Claude generates focused dashboards, tracks trends, and keeps everything organized across sessions

### Updating

```bash
cd ~/.claude/skills/health-skill && git pull
```

---

## Setup for Claude Code

```bash
# Clone and install
git clone https://github.com/googlarz/health-skill.git ~/.claude/skills/health-skill

# Initialize a person folder
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py init-project \
  --root ~/Health/mom --name "Mom"
```

Reference it in any project's `CLAUDE.md`:

```md
Use /health-skill

This is a health workspace for Mom.
Always read HEALTH_DOSSIER.md before answering health questions.
```

### CLI Quick Reference

| I want to... | Command |
|---|---|
| Set up a new person folder | `init-project --root . --name "Name"` |
| Process new documents | Drop into `inbox/`, then `process-inbox --root .` |
| See what's important now | Open `TODAY.md` or `HEALTH_HOME.md` |
| Prepare for an appointment | `query-dashboard --root . --query "visit prep"` |
| Ask a health question | `query-dashboard --root . --query "your question"` |
| Check extraction accuracy | `extraction-audit --root .` |

See [docs/commands.md](docs/commands.md) for the full reference.

---

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

**Query-relevant dashboards** — Ask any health question and get a focused view with only the relevant data, not the full dossier. Dashboards can be saved and reused for similar future queries.

**Trust-aware extraction** — Facts extracted from documents are labeled by confidence. OCR-derived data is flagged for review. You confirm what matters.

**Medication safety** — Adding a medication that conflicts with a known allergy triggers a warning automatically.

**Pattern detection** — Connects labs to medications to follow-ups over time. Flags stale tests, temporal side-effect correlations, and overdue follow-ups.

**Visual outputs** — Status chips (✅/⚠️), sparkline charts, trend arrows, and bold key numbers. Designed for scanning when tired or stressed.

**Caregiver dashboard** — One view across multiple person folders with urgency scoring and follow-up reminders.

## Who This Is For

- Managing your own recurring appointments, labs, and medications
- Helping a parent, partner, or child with health admin
- Keeping Claude useful across months, not just one conversation

## What It Is Not

- Not a doctor, diagnostic system, or prescribing tool
- Not a HIPAA-compliant platform
- Not a replacement for emergency care or licensed clinicians

See [references/safety-protocol.md](references/safety-protocol.md) for the full safety model.

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
