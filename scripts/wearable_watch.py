#!/usr/bin/env python3
"""macOS launchd watcher for automatic wearable sync.

Installs a launchd job that runs `sync-wearable` every hour so Health Auto
Export (or any other tool that drops files into inbox/wearable/) is picked up
automatically without any manual step.

Usage:
    scripts/care_workspace.py setup-watch --root ~/Health/me --person-id me
    scripts/care_workspace.py setup-watch --root ~/Health/me --person-id me --uninstall
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PLIST_LABEL_PREFIX = "com.health-skill.wearable-sync"


def _plist_label(person_id: str) -> str:
    safe = person_id.replace(" ", "_").lower() if person_id else "default"
    return f"{PLIST_LABEL_PREFIX}.{safe}"


def _plist_path(person_id: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_plist_label(person_id)}.plist"


def _script_path() -> Path:
    """Return absolute path to care_workspace.py (the CLI entry point)."""
    return Path(__file__).parent / "care_workspace.py"


def install_launchd_watcher(root: Path, person_id: str, interval_seconds: int = 3600) -> Path:
    """Install (or replace) a launchd job that runs sync-wearable periodically.

    Returns the path to the plist file created.
    """
    label = _plist_label(person_id)
    plist = _plist_path(person_id)
    python = sys.executable
    script = str(_script_path().resolve())
    root_abs = str(root.resolve())
    log_dir = root.resolve() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = str(log_dir / "wearable-sync.log")
    stderr_log = str(log_dir / "wearable-sync-error.log")

    # Unload existing job silently if present
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
        <string>sync-wearable</string>
        <string>--root</string>
        <string>{root_abs}</string>
        <string>--person-id</string>
        <string>{person_id}</string>
    </array>

    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
</dict>
</plist>
"""
    plist.write_text(plist_content, encoding="utf-8")

    result = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"launchctl load failed: {result.stderr.strip()}")

    return plist


def uninstall_launchd_watcher(person_id: str) -> bool:
    """Unload and remove the launchd plist. Returns True if it existed."""
    plist = _plist_path(person_id)
    if not plist.exists():
        return False
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    plist.unlink()
    return True


def watcher_status(person_id: str) -> dict[str, object]:
    """Return install status of the launchd watcher."""
    plist = _plist_path(person_id)
    label = _plist_label(person_id)
    installed = plist.exists()
    running = False
    if installed:
        result = subprocess.run(
            ["launchctl", "list", label], capture_output=True, text=True
        )
        running = result.returncode == 0
    return {"installed": installed, "running": running, "plist": str(plist), "label": label}
