"""Regression tests for the two security findings from the September audit:
path traversal via person_id, and plist XML injection in the launchd watcher.
"""

import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.wearable_watch as wearable_watch
from scripts.care_workspace import person_dir, profile_path
from scripts.wearable_watch import _plist_label, install_launchd_watcher

# install_launchd_watcher writes to the real ~/Library/LaunchAgents and shells
# out to launchctl -- both macOS-only, and CI runs on Linux. Patch the plist
# location into a temp dir and stub launchctl so the actual security property
# (plistlib serialization can't be injected into) is verified on every
# platform, not skipped on the one CI actually runs on.
_FAKE_LAUNCHCTL = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


class PathTraversalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_dotdot_person_id_rejected(self):
        with self.assertRaises(ValueError):
            person_dir(self.root, "../../../../tmp/pwned")

    def test_forward_slash_person_id_rejected(self):
        with self.assertRaises(ValueError):
            person_dir(self.root, "foo/bar")

    def test_backslash_person_id_rejected(self):
        with self.assertRaises(ValueError):
            person_dir(self.root, "foo\\bar")

    def test_bare_dotdot_rejected(self):
        with self.assertRaises(ValueError):
            person_dir(self.root, "..")

    def test_derived_path_functions_also_protected(self):
        with self.assertRaises(ValueError):
            profile_path(self.root, "../../etc/passwd")

    def test_legit_person_id_unaffected(self):
        self.assertEqual(person_dir(self.root, "dad"), self.root / "people" / "dad")

    def test_empty_person_id_unaffected(self):
        self.assertEqual(person_dir(self.root, ""), self.root)


class PlistInjectionTests(unittest.TestCase):
    PAYLOAD = "</string></array><key>Pwned</key><true/><key>ProgramArguments</key><array><string>x"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.workspace = self.tmp / "workspace"
        self.plists_dir = self.tmp / "LaunchAgents"
        self.plists_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _install(self, person_id: str):
        with patch.object(wearable_watch, "_plist_path",
                           lambda pid: self.plists_dir / f"{_plist_label(pid)}.plist"), \
             patch.object(wearable_watch.subprocess, "run", return_value=_FAKE_LAUNCHCTL):
            return install_launchd_watcher(self.workspace, person_id, interval_seconds=60)

    def test_malicious_person_id_does_not_inject_plist_keys(self):
        plist = self._install(self.PAYLOAD)
        parsed = plistlib.loads(plist.read_bytes())
        self.assertNotIn("Pwned", parsed)
        # the payload must survive as an inert string argument, not plist structure
        self.assertIn(self.PAYLOAD, parsed["ProgramArguments"])

    def test_plist_label_has_no_path_separators(self):
        label = _plist_label("../../etc/evil")
        self.assertNotIn("/", label)
        self.assertNotIn("\\", label)

    def test_normal_person_id_still_installs(self):
        plist = self._install("dad")
        self.assertTrue(plist.exists())
        parsed = plistlib.loads(plist.read_bytes())
        self.assertIn("dad", parsed["ProgramArguments"])


if __name__ == "__main__":
    unittest.main()
