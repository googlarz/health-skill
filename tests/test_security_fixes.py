"""Regression tests for the two security findings from the September audit:
path traversal via person_id, and plist XML injection in the launchd watcher.
"""

import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import person_dir, profile_path
from scripts.wearable_watch import (
    _plist_label,
    install_launchd_watcher,
    uninstall_launchd_watcher,
)


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

    def tearDown(self):
        uninstall_launchd_watcher(self.PAYLOAD)
        uninstall_launchd_watcher("dad")

    def test_malicious_person_id_does_not_inject_plist_keys(self):
        root = Path(tempfile.mkdtemp())
        try:
            plist = install_launchd_watcher(root, self.PAYLOAD, interval_seconds=60)
            parsed = plistlib.loads(plist.read_bytes())
            self.assertNotIn("Pwned", parsed)
            # the payload must survive as an inert string argument, not plist structure
            self.assertIn(self.PAYLOAD, parsed["ProgramArguments"])
        finally:
            shutil.rmtree(root)

    def test_plist_label_has_no_path_separators(self):
        label = _plist_label("../../etc/evil")
        self.assertNotIn("/", label)
        self.assertNotIn("\\", label)

    def test_normal_person_id_still_installs(self):
        root = Path(tempfile.mkdtemp())
        try:
            plist = install_launchd_watcher(root, "dad", interval_seconds=60)
            self.assertTrue(plist.exists())
            parsed = plistlib.loads(plist.read_bytes())
            self.assertIn("dad", parsed["ProgramArguments"])
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
