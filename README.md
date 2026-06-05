<p align="center">
  <h1 align="center">Health Skill</h1>
  <p align="center">
    A health workspace and longevity companion for Claude — connects your labs, medications, training, sleep, and family history so you can get more out of every conversation and every doctor's visit.
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/tests-265%20passing-brightgreen" alt="Tests">
    <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/version-2.3-purple" alt="v2.3">
  </p>
</p>

---

> Claude that remembers your health history — and reasons across all of it.

Most health conversations with AI start from scratch. Health Skill gives Claude a **persistent workspace** that connects your labs to your medications, your sleep to your pain, your family history to your screening schedule — so every conversation builds on the last.

It's also a **daily longevity companion**: log check-ins, track your cycle, design training plans, monitor preventive care, sync your watch automatically, and discover patterns across your entire health picture.

## Contents

- [Setup for Claude Cowork](#setup-for-claude-cowork)
- [Wearable & Apple Health Sync](#wearable--apple-health-sync)
- [Setup for Claude Code](#setup-for-claude-code)
- [What You Get](#what-you-get)
- [Key Features](#key-features)
- [Recent Releases](#recent-releases)
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

## Wearable & Apple Health Sync

Health Skill can import data from any fitness watch or wearable. There are two paths:

> **Suunto users:** there's a dedicated [suunto-mcp](https://github.com/googlarz/suunto-mcp) server that connects your Suunto watch directly to Claude via the official Suunto API — live workouts, HRV, sleep, and GPX export without any manual export steps. Install it alongside Health Skill for a fully automated pipeline.

**Option A — Via Apple Health (iPhone users)**
Most watches (Garmin, Suunto, Polar, Whoop, Oura, Amazfit, Withings) sync to Apple Health through their companion app. From Apple Health you can export data and drop it into your workspace `inbox/wearable/` folder, or use an Apple Health export app of your choice to automate the transfer to iCloud Drive.

**Option B — Direct from your watch app**
Many watch brands let you export workouts or health data directly from their app as CSV or JSON — no Apple Health needed. Drop the file into `inbox/wearable/` and run `import-wearable`.

**Option C — Manual CSV/JSON drop**
Any CSV or JSON with columns for date, steps, heart rate, sleep, etc. is accepted. Drop it in `inbox/wearable/` and run `import-wearable`.

Once files land in `inbox/wearable/`, install the background watcher to import them automatically:

```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me \
  --person-id me
```

**Check that it's running:**
```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me --person-id me --status
```

**See the logs:**
```bash
tail -f ~/Health/me/logs/wearable-sync.log
```

**Uninstall:**
```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me --person-id me --uninstall
```

---

### What gets imported

| Metric | Source |
|--------|--------|
| Steps | Garmin, Suunto, Polar, Whoop, Oura, Amazfit, Withings, iPhone |
| Resting heart rate | All watches |
| Heart rate variability (HRV) | Garmin, Whoop, Oura, Polar |
| VO2 max | Garmin, Polar, Apple Watch |
| Weight | Withings scale, Garmin scale, manual entry |
| Blood pressure | Withings BP monitor, Omron (via Health) |
| Sleep hours | All watches with sleep tracking |
| SpO2 | Garmin, Oura, Whoop, Amazfit, Apple Watch |

---

### Multiple people, multiple watches

Each person folder gets its own watcher:

```bash
# Install watcher for mom's folder
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/mom --person-id mom

# Install watcher for your own folder
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me --person-id me
```

Each runs independently. If you manage data for a parent who doesn't have their own Mac, drop their exports manually into their inbox folder — the watcher will pick them up on the next cycle.

---

### Troubleshooting

**iCloud folder not syncing to Mac**
Open System Settings → Apple ID → iCloud → iCloud Drive → make sure iCloud Drive is enabled and "Optimize Mac Storage" is OFF (otherwise files may not be local).

**Health Auto Export not writing files**
Open the app → tap your export → tap **Export Now** to test manually. Check that iCloud Drive is selected as the destination.

**Watcher installed but no data coming in**
```bash
# Check the error log
cat ~/Health/me/logs/wearable-sync-error.log

# Run manually to see output
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py sync-wearable \
  --root ~/Health/me --person-id me
```

**Watch data not appearing in Apple Health**
In the Health app on iPhone, go to **Sharing** → **Apps** → find your watch app → make sure it has permission to write the metrics you care about.

---

## Auto-ingest hooks

Health Skill includes Claude Code hooks that **automatically save health data from every message** — workouts, check-ins, labs, weight, symptoms, medication mentions — without you having to run a command.

**What gets saved:**
- Text: "ran 5km in 28 min" → workout entry with date
- Text: "I feel sick, weight 85kg" → symptom check-in + weight entry
- File reads: lab CSV, workout export → structured entries extracted from content
- Photos: Claude extracts data and saves it (see [photo-handling.md](references/photo-handling.md))

**Install:**
```bash
git clone https://github.com/googlarz/health-skill.git
bash health-skill/hooks/install.sh
```

Data is saved to your workspace as dated entries in `HEALTH_TIMELINE.md` (markdown workspaces) or directly into the structured profile (JSON workspaces). After each response, Claude shows what was auto-saved.

**Works with any workspace layout** — the hooks detect your workspace root and the right person automatically from the current project directory.

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

> **Tip:** Set `export HEALTH_ROOT=~/Health/me` once in your shell profile and drop `--root .` from every command.

| I want to... | Command |
|---|---|
| **Start a health conversation** | `hi` · `hello` · `hey` |
| **See what needs attention** | `status` |
| Set up a new person folder | `init-project --root . --name "Name"` |
| Run onboarding | `onboard --root .` |
| Process new documents | Drop into `inbox/`, then `process-inbox --root .` |
| Prepare for an appointment | `query-dashboard --root . --query "visit prep"` |
| Ask a health question | `query-dashboard --root . --query "your question"` |
| Log a daily check-in | `daily-checkin --root . --note "mood 8, slept 7h, energy good"` |
| Log a workout | `log-workout --root . --type strength --duration 45 --notes "squats, deadlifts"` |
| Generate a training plan | `workout-plan --root . --goals "build strength" --days 3` |
| Run metrics summary | `run-summary --root . --n 5` |
| Log a screening | `screening-log --root . --name mammogram --date 2024-06-01` |
| See overdue screenings | `preventive-check --root .` |
| Discover cross-domain patterns | `connections --root .` |
| **Get proactive nudges** | `nudges --root .` |
| **Generate weekly recap** | `weekly-recap --root . --days 7` |
| **Set a longevity goal** | `add-goal --root . --title "LDL under 130" --metric ldl --target 130` |
| **Show goals & progress** | `goals --root .` |
| **Add a care-team provider** | `add-provider --root . --name "Dr Smith" --role pcp` |
| **Import wearable data** | `import-wearable --root . --file inbox/export.xml` |
| **Run structured triage** | `triage --root . --summary "knee pain" --q1 "..." --q2 "..."` |
| **Forecast labs and weight** | `forecast --root .` |
| **Generate lab-to-action plan** | `lab-actions --root .` |
| **Log a meal** | `log-meal --root . --text "chicken 200g, rice 1 cup, broccoli"` |
| **Nutrition trends** | `nutrition --root .` |
| **HRT / statin / screening decision aid** | `decide --root . --topic hrt` |
| **Auto-sync wearable inbox** | `sync-wearable --root .` |
| **Add household member** | `household-add-member --root . --id self --name "Anna" --folder anna` |
| **Cascade family history** | `household-cascade --root .` |
| **Check drug & supplement interactions** | `check-interactions --root .` |
| **Medication summary card** | `med-summary --root .` |
| **Explain a lab result** | `explain-lab --root . --marker LDL --value 155` |
| **Medication side-effect timeline** | `side-effects --root .` |
| **Monthly insight report** | `monthly-report --root .` |
| **Import FHIR from patient portal** | `import-fhir --root . --file inbox/fhir.json` |
| **Mental health screen** | `mental-health --root .` |
| **Log an intervention** | `log-intervention --root . --name "16:8 fasting" --start-date 2025-01-15 --protocol "..." --outcome-metric weight_kg` |
| **Intervention progress** | `intervention-status --root .` |

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

---

## Key Features

**👋 Conversational check-in (`hi`)** — Just say `hi`. The skill reads your workspace, picks the single most relevant thing going on right now, and opens a conversation around it. High pain this week? It asks. Active intervention? It checks in on your progress. Appointment tomorrow? It offers to prep. No dashboards, no lists — just the right question at the right time.

```
$ hi

Hey Anna! I noticed your pain has been averaging around 7/10 over
the last week. How are you feeling today — any better, or still
about the same?
```

**🔍 Query-relevant dashboards** — Ask any health question and get a focused view with only the relevant data, not the full dossier. Dashboards are saved and reused for similar future queries.

**💊 Drug & supplement interaction checker** — `check-interactions` scans your medications and supplements against 20+ drug–drug and 6 supplement–drug pairs. Alerts sorted major → moderate, each with mechanism and action. `med-summary` renders a medication card with interaction warnings per drug.

**🧪 Lab explanation** — `explain-lab --marker LDL --value 155` gives a plain-English 4-sentence interpretation personalised to your age, sex, conditions, and medications. Not a generic normal-range lookup — your context, your number.

**📐 Personalised lab ranges** — `lab-range` adjusts reference ranges for your conditions and medications: LDL target tightens with diabetes, TSH narrows on levothyroxine, haemoglobin adjusts by sex. Flags are green/amber/red against your range, not population averages.

**🏃 Run metrics** — `run-summary` shows your last N runs with pace, HR, TSS, and VO2max deltas vs the prior run. Trend labels (`↑ pace improving`, `⚠ cardiac drift`) make the numbers readable at a glance.

**🎯 Intervention tracker** — `log-intervention` tracks named lifestyle protocols (16:8 fasting, zone-2 training, cold exposure) with start date, protocol, outcome metric, and days running. `intervention-status` surfaces the latest tracked value.

**🔔 Proactive nudges** — `nudges` scans for overdue follow-ups, stale labs, missed check-ins, conflicts, chronic sleep deficit, sustained low mood/energy, high pain streaks, non-dipping BP patterns, and rapid weight gain. Each nudge includes a copy-pasteable command to act on it.

**📈 Medication side-effect timeline** — `side-effects` correlates medication start dates with your daily check-ins. Pain up 3 points after starting a statin? Sleep disrupted after an SSRI? Signal surfaces automatically.

**🧠 Mental health layer** — `mental-health` runs PHQ-2 and GAD-2 proxies from check-in data plus a burnout detector. Includes crisis resources.

**🧬 Pharmacogenomics** — `import-pgx` parses 23andMe/AncestryDNA raw files and calls CYP2C19, CYP2D6, CYP2C9, SLCO1B1, VKORC1, MTHFR, DPYD phenotypes. `pgx-report` flags your current medications against your genotype — clopidogrel + CYP2C19 poor metaboliser is a critical alert.

**📊 Visual dashboard** — `dashboard` generates a self-contained HTML file: 30-day KPI cards, 90-day trend charts, weight timeline, labs plotted against your personalised ranges, active medications, appointments. No server needed.

**👨‍👩‍👧 Household graph** — `household-add-member` + `household-cascade` push a parent's diagnosed condition into every connected member's family history automatically, adjusting their screening dates.

**🔮 Forecasting** — `forecast` projects lab markers and weight forward 3–6 months using linear regression with 95% confidence intervals. "At this rate you hit your LDL goal by August."

**🍽 Nutrition tracker** — `log-meal "chicken 200g, rice 1 cup, broccoli"` parses ~80 common foods into macros, aggregates 14-day trends, coaches on gaps.

**⌚ Wearable sync** — drop Apple Health export or any CSV in `inbox/`, run `import-wearable`. Install the background watcher for daily auto-sync.

**👪 Family-history-aware screening** — adding "Mom: breast cancer at 48" pulls mammogram start age forward to 38 automatically.

---

## Recent Releases

### v2.3 — Conversational UX overhaul
- **`hi` / `hello` / `hey`** — context-aware greeting that opens with the one thing that matters most right now
- **`status`** — one-glance workspace summary with nudge counts, last check-in, and quick actions
- **`HEALTH_ROOT` env var** — set once, skip `--root .` forever
- **`explain-lab`** — plain-English lab explanation personalised to your profile
- **`med-summary`** — medication card with per-drug interaction warnings
- **Natural language check-ins** — "exhausted", "can't sleep", "bad pain", "stressed" all parse correctly
- **Friendly errors** — missing workspace, unknown path: clear hints instead of tracebacks
- **Nudges with commands** — every nudge now includes a copy-pasteable action command
- **Interaction urgency ranking** — alerts sorted major → moderate with summary header
- **Run metrics trend labels** — `↑ pace improving`, `⚠ cardiac drift`, avg footer
- **Weekly recap headline** — "best day" opener + "one thing to focus on" footer
- **`--dry-run`** on `resolve-review-item` and `apply-review-tier`
- **Command aliases** — `log-workout`, `log-checkin`, `interactions`, `meds`, `labs`

### v2.2.1 — Clinical depth
- Supplement–drug interaction checker (nattokinase, fish oil, vitamin K2, beetroot, hibiscus, omega-3)
- Non-dipping BP pattern alert (nocturnal dip < 10% → cardiovascular risk flag)
- Run metrics schema: TSS, NGP, power, GCT, vertical oscillation, EPOC, PTE, cadence, stride, VO2max
- Intervention tracker: `log-intervention` + `intervention-status`

### v2.0 — Whole-person health
- Forecasting, lab-to-action, nutrition, decision support, live wearable sync, household graph

### v1.8 — Safety & clinical depth
- Drug–drug interaction checker, personalised lab ranges, side-effect timeline, monthly report, FHIR import, mental health layer, continuous pattern alerts, pharmacogenomics, appointment workflow, men's health module, visual HTML dashboard

---

## Who This Is For

- Managing your own recurring appointments, labs, and medications
- Helping a parent, partner, or child with health admin
- Keeping Claude useful across months, not just one conversation

## What It Is Not

- Not a doctor, diagnostic system, or prescribing tool
- Not a HIPAA-compliant platform
- Not a replacement for emergency care or licensed clinicians

See [references/safety-protocol.md](references/safety-protocol.md) for the full safety model.

---

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
python3 -m pytest tests/ -q   # 265 tests, ~2s
```

## License

[MIT](LICENSE)
