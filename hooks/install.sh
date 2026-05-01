#!/usr/bin/env bash
# Install Health Skill auto-ingest hooks into ~/.claude/settings.json
# Hooks silently parse health data from every message and file read,
# saving structured entries to your workspace timeline.
#
# Usage: bash hooks/install.sh [--claude-config-dir DIR]

set -euo pipefail

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CONFIG_DIR/settings.json"
HOOKS_DEST="$CONFIG_DIR/hooks"

# Create hooks dir in Claude config
mkdir -p "$HOOKS_DEST"

# Copy hook scripts
cp "$HOOKS_DIR/health-auto-ingest.py" "$HOOKS_DEST/"
cp "$HOOKS_DIR/health-file-ingest.py" "$HOOKS_DEST/"
echo "✓ Hooks copied to $HOOKS_DEST"

# Ensure settings.json exists
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
fi

# Validate existing JSON
if ! python3 -c "import json; json.load(open('$SETTINGS'))" 2>/dev/null; then
  echo "❌ $SETTINGS contains invalid JSON. Fix it first."
  exit 1
fi

# Merge hooks using Python
python3 << PYEOF
import json, sys
from pathlib import Path

settings_path = Path("$SETTINGS")
s = json.loads(settings_path.read_text())
hooks = s.setdefault("hooks", {})

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

# UserPromptSubmit
ups = hooks.setdefault("UserPromptSubmit", [])
if not hook_exists(ups, "health-auto-ingest"):
    ups.append({"hooks": [{"type": "command", "command": auto_ingest_cmd}]})
    print("✓ UserPromptSubmit hook added")
else:
    print("· UserPromptSubmit hook already present")

# Stop
stop = hooks.setdefault("Stop", [])
if not hook_exists(stop, "health-ingest"):
    stop.append({"hooks": [{"type": "command", "command": stop_cmd}]})
    print("✓ Stop hook added")
else:
    print("· Stop hook already present")

# PostToolUse:Read
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

echo ""
echo "✅ Health Skill hooks installed."
echo "   Restart Claude Code or open /hooks to activate."
echo ""
echo "Optional: set HEALTH_WORKSPACE_ROOT=/path/to/your/workspace"
echo "  to force a specific workspace regardless of project directory."
