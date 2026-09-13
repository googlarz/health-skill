"""Conditions recorded in Chinese must cascade like their English equivalents.

CASCADE_TERMS held English literals only, so a profile built from Chinese
reports matched nothing and cascade_family_history() silently added zero
entries -- a first-degree prostate cancer would not reach the child's family
history even though "prostate cancer" was on the list.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import care_workspace as cw
import household as hh

# One Chinese phrasing per condition already on the English list, written the way
# a report states it rather than as a bare term.
EQUIVALENTS = [
    ("乳腺癌", "breast cancer"),
    ("卵巢癌", "ovarian cancer"),
    ("结直肠癌", "colorectal cancer"),
    ("前列腺癌(前列腺根治切除术后约8年)", "prostate cancer"),
    ("黑色素瘤", "melanoma"),
    ("宫颈癌", "cervical cancer"),
    ("急性心肌梗死", "myocardial infarction"),
    ("脑梗死", "stroke"),
    ("心源性猝死", "early cardiac death"),
    ("2型糖尿病", "diabetes"),
    ("阿尔茨海默病", "alzheimer"),
    ("帕金森病", "parkinson"),
]


class CascadeTermTests(unittest.TestCase):
    def test_chinese_conditions_cascade(self) -> None:
        for chinese, english in EQUIVALENTS:
            with self.subTest(condition=chinese):
                self.assertTrue(
                    hh._condition_should_cascade(chinese),
                    f"{chinese!r} is {english}, which is already on CASCADE_TERMS",
                )

    def test_english_terms_still_cascade(self) -> None:
        for _, english in EQUIVALENTS:
            with self.subTest(condition=english):
                self.assertTrue(hh._condition_should_cascade(english))

    def test_unrelated_conditions_do_not_cascade(self) -> None:
        # Real entries from a Chinese checkup report that are not heritable
        # markers; adding Chinese aliases must not widen the condition set.
        for condition in ("脂肪肝", "双肾多发囊肿 + 双肾结晶", "慢性肺部病变", "甲状腺结节"):
            with self.subTest(condition=condition):
                self.assertFalse(
                    hh._condition_should_cascade(condition),
                    f"{condition!r} is not on the heritable list and must not cascade",
                )

    def test_chinese_condition_reaches_a_childs_family_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for person_id in ("father", "child"):
                cw.ensure_person(root, person_id, person_id)
            hh.add_member(root, "father", "父", folder="father")
            hh.add_member(root, "child", "子", folder="child")
            hh.add_relationship(root, "child", "father", "father")

            profile = cw.load_profile(root, "father")
            profile.setdefault("conditions", []).append(
                {"name": "前列腺癌(前列腺根治切除术后约8年)"}
            )
            profile["conditions"].append({"name": "脂肪肝"})
            cw.save_profile(root, "father", profile)

            hh.cascade_family_history(root)

            history = cw.load_profile(root, "child").get("family_history", [])
            conditions = [entry.get("condition") for entry in history]
            self.assertTrue(
                any("前列腺癌" in (c or "") for c in conditions),
                f"child inherited {conditions}, expected the father's prostate cancer",
            )
            self.assertFalse(
                any("脂肪肝" in (c or "") for c in conditions),
                f"child inherited {conditions}; 脂肪肝 is not heritable and must not cascade",
            )


if __name__ == "__main__":
    unittest.main()
