#!/usr/bin/env bash
# Install Health Skill auto-ingest hooks into ~/.claude/settings.json
# Hooks silently parse health data from every message and file read,
# saving structured entries to your workspace timeline.
#
# Usage: bash hooks/install.sh

set -euo pipefail

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CONFIG_DIR/settings.json"
HOOKS_DEST="$CONFIG_DIR/hooks"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║        Health Skill — Hook Installer         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: Workspace ─────────────────────────────────────────────────────────

DEFAULT_WORKSPACE="$HOME/Health"
echo "Where is your health workspace folder?"
echo "  (A folder where each person has their own subfolder, e.g. ~/Health/Alice)"
printf "  Press Enter for [$DEFAULT_WORKSPACE], or type a path: "
read -r WORKSPACE_INPUT
WORKSPACE="${WORKSPACE_INPUT:-$DEFAULT_WORKSPACE}"
WORKSPACE="${WORKSPACE/#\~/$HOME}"  # expand ~ manually

# ── Step 2: People ────────────────────────────────────────────────────────────

echo ""
# Detect existing person folders
EXISTING_PEOPLE=()
if [ -d "$WORKSPACE" ]; then
  while IFS= read -r -d '' dir; do
    name="$(basename "$dir")"
    if [ -f "$dir/HEALTH_PROFILE.md" ] || [ -f "$dir/profile.json" ]; then
      EXISTING_PEOPLE+=("$name")
    fi
  done < <(find "$WORKSPACE" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
fi

if [ ${#EXISTING_PEOPLE[@]} -gt 0 ]; then
  echo "Found existing people in $WORKSPACE:"
  for p in "${EXISTING_PEOPLE[@]}"; do
    echo "  · $p"
  done
  echo ""
  printf "Add more people? (comma-separated names, or Enter to skip): "
  read -r NEW_PEOPLE_INPUT
else
  echo "No people folders found in $WORKSPACE."
  printf "Who uses this workspace? (comma-separated names, e.g. Alice,Bob): "
  read -r NEW_PEOPLE_INPUT
fi

# Create new person folders
ALL_PEOPLE=("${EXISTING_PEOPLE[@]}")
if [ -n "$NEW_PEOPLE_INPUT" ]; then
  IFS=',' read -ra NEW_NAMES <<< "$NEW_PEOPLE_INPUT"
  for raw_name in "${NEW_NAMES[@]}"; do
    name="$(echo "$raw_name" | xargs)"  # trim whitespace
    [ -z "$name" ] && continue
    person_dir="$WORKSPACE/$name"
    if [ ! -d "$person_dir" ]; then
      mkdir -p "$person_dir"
      cat > "$person_dir/HEALTH_PROFILE.md" << MDEOF
# Health Profile — $name

*Created by Health Skill installer on $(date +%Y-%m-%d)*

## Personal

- **Name:** $name

## Conditions

*(none recorded yet)*

## Medications

*(none recorded yet)*

## Notes

*(add health notes here)*
MDEOF
      echo "✓ Created $person_dir/HEALTH_PROFILE.md"
    fi
    ALL_PEOPLE+=("$name")
  done
fi

# ── Step 3: Default person ────────────────────────────────────────────────────

DEFAULT_PERSON=""
if [ ${#ALL_PEOPLE[@]} -eq 1 ]; then
  DEFAULT_PERSON="${ALL_PEOPLE[0]}"
  echo ""
  echo "Default person on this computer: $DEFAULT_PERSON"
elif [ ${#ALL_PEOPLE[@]} -gt 1 ]; then
  echo ""
  echo "Who is the primary person on this computer?"
  for i in "${!ALL_PEOPLE[@]}"; do
    echo "  $((i+1)). ${ALL_PEOPLE[$i]}"
  done
  printf "  Enter number [1]: "
  read -r CHOICE
  CHOICE="${CHOICE:-1}"
  idx=$((CHOICE - 1))
  DEFAULT_PERSON="${ALL_PEOPLE[$idx]:-${ALL_PEOPLE[0]}}"
  echo "✓ Default person: $DEFAULT_PERSON"
fi

# ── Step 4: Install hooks ─────────────────────────────────────────────────────

echo ""
mkdir -p "$HOOKS_DEST"
cp "$HOOKS_DIR/health-auto-ingest.py" "$HOOKS_DEST/"
cp "$HOOKS_DIR/health-file-ingest.py" "$HOOKS_DEST/"
echo "✓ Hooks copied to $HOOKS_DEST"

# Ensure settings.json exists
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
fi

if ! python3 -c "import json; json.load(open('$SETTINGS'))" 2>/dev/null; then
  echo "❌ $SETTINGS contains invalid JSON. Fix it first."
  exit 1
fi

# Merge hooks + env vars into settings.json
python3 << PYEOF
import json, sys
from pathlib import Path

settings_path = Path("$SETTINGS")
s = json.loads(settings_path.read_text())
hooks = s.setdefault("hooks", {})

# Set env vars for workspace root and default person
env = s.setdefault("env", {})
workspace = "$WORKSPACE"
default_person = "$DEFAULT_PERSON"

if workspace:
    env["HEALTH_WORKSPACE_ROOT"] = workspace
    print(f"✓ HEALTH_WORKSPACE_ROOT = {workspace}")
if default_person:
    env["HEALTH_DEFAULT_PERSON"] = default_person
    print(f"✓ HEALTH_DEFAULT_PERSON = {default_person}")

auto_ingest_cmd = "python3 $HOOKS_DEST/health-auto-ingest.py 2>/dev/null || true"
file_ingest_cmd = "python3 $HOOKS_DEST/health-file-ingest.py 2>/dev/null || true"
stop_cmd = r"""python3 -c "
import json, sys, glob, os
files = glob.glob('/tmp/health-ingest-*.json')
if not files: sys.exit(0)
all_lines = []
for f in files:
    try:
        d = json.loads(open(f).read())
        all_lines.extend(d.get('lines', []))
        os.unlink(f)
    except: pass
if all_lines:
    msg = '\n'.join(all_lines)
    print(json.dumps({'systemMessage': '💾 Health data auto-saved:\n' + msg}))
" 2>/dev/null || true"""

def hook_exists(hook_list, cmd_substr):
    for entry in hook_list:
        for h in entry.get("hooks", []):
            if cmd_substr in h.get("command", ""):
                return True
    return False

ups = hooks.setdefault("UserPromptSubmit", [])
if not hook_exists(ups, "health-auto-ingest"):
    ups.append({"hooks": [{"type": "command", "command": auto_ingest_cmd}]})
    print("✓ UserPromptSubmit hook added")
else:
    print("· UserPromptSubmit hook already present")

stop = hooks.setdefault("Stop", [])
if not hook_exists(stop, "health-ingest"):
    stop.append({"hooks": [{"type": "command", "command": stop_cmd}]})
    print("✓ Stop hook added")
else:
    print("· Stop hook already present")

ptu = hooks.setdefault("PostToolUse", [])
if not hook_exists(ptu, "health-file-ingest"):
    ptu.insert(0, {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": file_ingest_cmd}]
    })
    print("✓ PostToolUse:Read hook added")
else:
    print("· PostToolUse:Read hook already present")

settings_path.write_text(json.dumps(s, indent=2))
print(f"✓ Settings written to {settings_path}")
PYEOF

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "✅ Health Skill hooks installed."
echo ""
echo "   Workspace : $WORKSPACE"
[ -n "$DEFAULT_PERSON" ] && echo "   Default   : $DEFAULT_PERSON"
echo ""
echo "   Restart Claude Code or open /hooks to activate."
echo ""
echo "   To change workspace or default person later, edit HEALTH_WORKSPACE_ROOT"
echo "   and HEALTH_DEFAULT_PERSON in ~/.claude/settings.json → env."
