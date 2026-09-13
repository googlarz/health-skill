"""Both supported workspace layouts must serve the caregiver overview and the
household family-history cascade.

A sibling-project workspace (root/<person>/) and a root/people/<id>/ workspace
used to be mutually exclusive: discover_projects() only scanned the root level
while person_dir() only resolved root/people/, so whichever layout satisfied one
feature broke the other.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import care_workspace as cw
import caregiver_dashboard as cd
import household as hh


def build(root: Path, layout: str) -> None:
    if layout == "nested":
        for person_id, name in (("dad", "Dad"), ("daughter", "Daughter")):
            cw.ensure_person(root, person_id, name)
    else:
        for person_id in ("dad", "daughter"):
            cw.ensure_person(root / person_id, "", person_id)
    hh.add_member(root, "dad", "Dad", folder="dad")
    hh.add_member(root, "daughter", "Daughter", folder="daughter")
    # add_relationship types describe "to" relative to "from": the daughter's father is dad.
    hh.add_relationship(root, "daughter", "dad", "father")
    profile = cw.load_profile(root, "dad")
    profile.setdefault("conditions", []).append({"name": "Type 2 Diabetes"})
    cw.save_profile(root, "dad", profile)


class WorkspaceLayoutTests(unittest.TestCase):
    def test_caregiver_overview_finds_every_person(self) -> None:
        for layout in ("nested", "flat"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build(root, layout)
                rows = cd.collect_project_rows(root)
                names = sorted(row["folder"] for row in rows)
                self.assertEqual(
                    names,
                    ["dad", "daughter"],
                    f"{layout} layout: overview saw {names}, expected both people",
                )

    def test_family_history_cascades_to_relatives(self) -> None:
        for layout in ("nested", "flat"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build(root, layout)
                hh.cascade_family_history(root)
                history = cw.load_profile(root, "daughter").get("family_history", [])
                conditions = [entry.get("condition") for entry in history]
                self.assertIn(
                    "Type 2 Diabetes",
                    conditions,
                    f"{layout} layout: daughter inherited {conditions}, expected dad's condition",
                )

    def test_person_dir_defaults_to_nested_for_new_people(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                cw.person_dir(root, "newcomer"),
                root / "people" / "newcomer",
                "an unknown person_id must still write into the root/people/ layout",
            )

    def test_sibling_project_only_wins_when_it_holds_a_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dad").mkdir()
            self.assertEqual(
                cw.person_dir(root, "dad"),
                root / "people" / "dad",
                "a bare sibling directory must not shadow the root/people/ layout",
            )


if __name__ == "__main__":
    unittest.main()
