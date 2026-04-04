# Setup Guide

## 5-Minute Setup For Non-Technical Users

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

Keep the unzipped `health-skill` folder somewhere you will not move around often.

Example:

```text
Documents/health-skill/
```

### 5. Initialize the person folder

```bash
python3 /absolute/path/to/health-skill/scripts/care_workspace.py init-project --root . --name "Jane Doe"
```

### 6. Start using it

- drop new health files into `inbox/`
- ask Claude to help you review the folder
- use `HEALTH_HOME.md`, `TODAY.md`, and `NEXT_APPOINTMENT.md` first

## Installation Options

### Option A: Local project toolkit (recommended)

- keep the `health-skill` folder on your machine
- use its scripts to initialize and maintain person folders
- open each person folder in Claude Cowork with `Use existing folder`

### Option B: Local skill folder

If your Claude setup supports local skills, place the whole `health-skill/` folder in your local skills directory.

## A Real Project Instruction Example

One of the best ways to use Health Skill is to layer project-specific rules on top of it:

```md
Use /health-skill

## Project Context

This is a family health management workspace. There are multiple person folders under `Health/`.

Examples:
- `Health/Person-A/`
- `Health/Person-B/`

Each person folder contains:
- HEALTH_PROFILE.md — structured health summary
- Lab result summaries (dated markdown files)
- Originals/ — source documents

## Default Behaviors

1. Always ask which person the request is about.
2. Read HEALTH_PROFILE.md first before answering any health question.
3. Follow the health-skill protocol for all health-related tasks.
4. Save outputs to the correct person folder.
5. Emergency rule is absolute.
```
