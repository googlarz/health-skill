#!/usr/bin/env python3
"""Wearable sync — auto-process anything in inbox/wearable/.

Watches the wearable inbox folder and, on demand, processes every file in it
using `wearable_import.import_wearable_file`. Successfully processed files are
moved to Archive/wearable/.

Pair with the iOS Shortcut recipe in references/wearable-sync.md to make Apple
Watch / iPhone health data flow automatically into the workspace.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .care_workspace import person_dir, wearable_inbox
    from .wearable_import import import_wearable_file
except ImportError:
    from care_workspace import person_dir, wearable_inbox  # type: ignore
    from wearable_import import import_wearable_file  # type: ignore


def sync_wearable_inbox(root: Path, person_id: str) -> dict[str, Any]:
    """Process every supported file in inbox/wearable/. Returns summary dict."""
    src = wearable_inbox(root, person_id)
    archive = person_dir(root, person_id) / "Archive" / "wearable"
    archive.mkdir(parents=True, exist_ok=True)

    summary = {
        "files_processed": 0,
        "files_skipped": 0,
        "totals": {},
        "errors": [],
    }
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".xml", ".csv"):
            summary["files_skipped"] += 1
            continue
        try:
            counts = import_wearable_file(root, person_id, f)
            for k, v in counts.items():
                summary["totals"][k] = summary["totals"].get(k, 0) + v
            # Move with date stamp
            target = archive / f"{date.today().isoformat()}-{f.name}"
            if target.exists():
                target = archive / f"{date.today().isoformat()}-{f.stem}-{summary['files_processed']}{f.suffix}"
            shutil.move(str(f), str(target))
            summary["files_processed"] += 1
        except Exception as e:  # pragma: no cover — best-effort import loop
            summary["errors"].append({"file": f.name, "error": str(e)})
    return summary
