<p align="center">
  <h1 align="center">Health Skill</h1>
  <p align="center">
    Local-first health workspace and longevity companion for Claude — organize records, track labs, log check-ins, plan training, prepare for visits, keep memory across sessions.
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/tests-146%20passing-brightgreen" alt="Tests">
    <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/version-2.0-purple" alt="v2.0">
  </p>
</p>

---

> One person = one folder. The folder is the memory, not the chat.

Health Skill gives Claude a **durable workspace** so it can reason across your full health picture — labs connected to medications connected to follow-ups — instead of starting from scratch every conversation.

It also works as a **daily longevity companion**: log how you feel, track your cycle, design training plans, monitor preventive care, and discover cross-domain patterns (sleep → pain → mood → labs).

## Contents

- [Setup for Claude Cowork](#setup-for-claude-cowork)
- [Setup for Claude Code](#setup-for-claude-code)
- [What You Get](#what-you-get)
- [Key Features](#key-features)
- [Longevity Companion (v1.7)](#longevity-companion-v17)
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
| Run onboarding | `onboard --root .` |
| Process new documents | Drop into `inbox/`, then `process-inbox --root .` |
| See what's important now | Open `TODAY.md` or `HEALTH_HOME.md` |
| Prepare for an appointment | `query-dashboard --root . --query "visit prep"` |
| Ask a health question | `query-dashboard --root . --query "your question"` |
| Log a daily check-in (full) | `daily-checkin --root . --note "mood 8, slept 7h, energy good"` |
| Log a daily check-in (shorthand) | `daily-checkin --root . --note "m8 s7 e7 p2"` |
| Log a workout | `workout-log --root . --type strength --duration 45 --notes "squats, deadlifts"` |
| Generate a training plan | `workout-plan --root . --goals "build strength" --days 3` |
| Log a screening | `screening-log --root . --name mammogram --date 2024-06-01` |
| See overdue screenings | `preventive-check --root .` |
| Discover cross-domain patterns | `connections --root .` |
| **Get proactive nudges** | `nudges --root .` |
| **Generate weekly recap** | `weekly-recap --root .` |
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

## What's new in v2.0

The skill is no longer a filing cabinet — it predicts, recommends actions, supports decisions, and works for whole households.

- **🔮 Forecasting** — `forecast` projects each lab marker and weight forward 3–6 months using linear regression with 95% confidence intervals. "At this rate you hit your LDL goal by August."
- **⚙️ Lab-to-action** — `lab-actions` turns every abnormal lab into a clinician question + lifestyle consideration + recheck cadence + drafted portal message. The loop from result to action becomes one click.
- **🍽 Nutrition tracker** — `log-meal "chicken 200g, rice 1 cup, broccoli"` parses ~80 common foods into calories/protein/fiber/sodium, aggregates 14-day trends, coaches on gaps.
- **🧭 Decision support** — `decide --topic hrt|statin|screening` produces structured shared-decision-making aids personalised to your data: pros, cons, what's missing, questions to bring.
- **⌚ Live wearable sync** — `sync-wearable` processes everything in `inbox/wearable/`. Pair with the iOS Shortcut recipe in [`references/wearable-sync.md`](references/wearable-sync.md) for daily auto-sync from your Apple Watch.
- **👨‍👩‍👧 Household / family graph** — `household-add-member` + `household-cascade` push a parent's diagnosed cancer or cardiac event into every connected member's family history automatically, which adjusts their preventive screening dates.

---

## What's new in v1.8

- **📸 Photo input** — paste a posture photo, skin lesion, medication bottle, lab screenshot, or food photo. See [`references/photo-handling.md`](references/photo-handling.md) for the full protocol.
- **🔔 Proactive nudges** — `nudges` scans the workspace for overdue items, stale labs, missed check-ins, open conflicts, and surfaces what to act on next.
- **📅 Weekly recap** — `weekly-recap` summarises your last 7 days: mood/sleep/energy/pain trends, training volume, weight delta, and one thing to action.
- **🎯 Goal tracking** — set quantified goals (LDL <130, deadlift 60kg, sleep 7+h) with `add-goal`. Baseline captured automatically; progress computed from your actual data.
- **⌚ Wearable import** — drop Apple Health `export.xml` or any CSV in `inbox/`, run `import-wearable`. Imports steps, RHR, VO2 max, SpO2, weight, BP, sleep.
- **👪 Family-history-aware screening** — adding "Mom: breast cancer at 48" pulls your mammogram start age forward to 38 automatically.
- **🩺 Provider directory** — store your care team (PCP, gyno, cardio, PT, dentist) with `add-provider`.
- **🧭 Structured triage** — describe a symptom, get walked through 5 questions, returns urgency band + red-flag detection + drafted clinician handoff.
- **⚡ Shorthand check-ins** — `m7 s7 e6 p2` works as well as a sentence. Lower friction = more data.
- **💡 Smart in-conversation suggestions** — Claude offers concrete next steps when you mention symptoms, sleep, new meds, family history, or goals.

---

## Longevity Companion (v1.7)

Health Skill isn't just for paperwork. It's a daily companion for people who want to stay healthy over the long term.

### Daily check-ins

Log how you feel in plain language. Claude parses it and stores structured data:

```
"mood 7, slept 6 hours, knee hurts 3/10, energy low"
```

Trends surface over time — sleep vs energy, pain vs training load, mood across the cycle.

### Cycle tracking (opt-in)

Log periods, symptoms, and cycle events. Claude predicts your next period, tracks cycle length, and connects cycle phase to mood and energy data if you log check-ins. Fully opt-in — set `track_cycles: true` in your profile.

### Training plans

Tell Claude your goals and constraints. It generates a weekly plan:

```
"fix my posture, 3 days a week, 30 minutes, bad lower back"
```

Plans are injury-aware and include progression. Log workouts with `workout-log`. PRs tracked automatically.

### Menopause & hormonal health

Health Skill has specific knowledge of perimenopause and menopause:

- **HRT context** — explains estrogen, progesterone, and testosterone therapy options; connects HRT to labs (lipids, bone markers); flags when symptoms warrant a conversation with a clinician
- **Symptom tracking** — hot flashes, sleep disruption, mood, joint pain, brain fog tracked in daily check-ins and connected to cycle data
- **Exercise guidance** — recommends compound/strength training for bone density preservation, explains why resistance training matters more post-menopause than cardio alone
- **Lab interpretation** — FSH, LH, estradiol, SHBG in context of where you are in the transition

### Preventive care

Tracks screenings by age and sex: mammogram, colonoscopy, bone density (DEXA), cervical cancer, blood pressure, cholesterol, diabetes, skin checks, eye exams, and more. Tells you what's overdue and when things are due next.

### Cross-domain connections

The connections engine looks across all your data and surfaces patterns you wouldn't notice manually:

- Sleep quality → next-day pain level
- Training frequency → resting heart rate trend
- Cycle phase → mood and energy check-ins
- LDL trend → exercise frequency correlation
- Weight → sleep quality over time

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
