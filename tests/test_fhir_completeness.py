"""Completeness guard for FHIR import: no clinically-relevant resource type may be
silently dropped. Every resource in a realistic patient-portal bundle must be either
(a) merged into the profile, or (b) reported under a "skipped_<ResourceType>" key —
never absorbed with no trace. Mirrors the pgx red-team guard: absence of handling is
not the same as absence of clinical content, and must never be mistaken for it.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile
from scripts.fhir_import import (
    _ADMINISTRATIVE_RESOURCE_TYPES,
    import_fhir_file,
)

# One resource of every type commonly present in a real Epic/Cerner MyChart export.
# resourceType -> minimal valid resource body.
REALISTIC_BUNDLE_RESOURCES = {
    "Patient": {"resourceType": "Patient", "id": "1"},
    "Encounter": {"resourceType": "Encounter", "status": "finished"},
    "Practitioner": {"resourceType": "Practitioner", "name": [{"text": "Dr Smith"}]},
    "Organization": {"resourceType": "Organization", "name": "General Hospital"},
    "Condition": {
        "resourceType": "Condition",
        "code": {"text": "Hypertension"},
        "clinicalStatus": {"coding": [{"code": "active"}]},
    },
    "MedicationRequest": {
        "resourceType": "MedicationRequest",
        "status": "active",
        "medicationCodeableConcept": {"text": "Lisinopril 10mg"},
    },
    "AllergyIntolerance": {
        "resourceType": "AllergyIntolerance",
        "code": {"text": "Penicillin"},
    },
    "Immunization": {
        "resourceType": "Immunization",
        "vaccineCode": {"text": "Influenza"},
        "occurrenceDateTime": "2025-10-01",
    },
    "Observation": {
        "resourceType": "Observation",
        "code": {"coding": [{"system": "http://loinc.org", "code": "2093-3"}]},
        "effectiveDateTime": "2025-06-01",
        "valueQuantity": {"value": 150, "unit": "mg/dL"},
    },
    "DiagnosticReport": {
        "resourceType": "DiagnosticReport",
        "code": {"text": "Chest X-ray"},
        "effectiveDateTime": "2025-05-01",
        "conclusion": "No acute findings.",
    },
    "Procedure": {
        "resourceType": "Procedure",
        "code": {"text": "Appendectomy"},
        "status": "completed",
    },
    "CarePlan": {"resourceType": "CarePlan", "status": "active"},
    "DocumentReference": {"resourceType": "DocumentReference", "status": "current"},
    "FamilyMemberHistory": {
        "resourceType": "FamilyMemberHistory",
        "relationship": {"text": "Mother"},
    },
    "Goal": {"resourceType": "Goal", "description": {"text": "Lower blood pressure"}},
    "ServiceRequest": {"resourceType": "ServiceRequest", "status": "active"},
}

# Everything not in this handled set must show up as merged content or "skipped_*".
_HANDLED_TYPES = {
    "Condition", "MedicationRequest", "MedicationStatement",
    "AllergyIntolerance", "Immunization", "Observation", "DiagnosticReport",
}


class FHIRCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1985-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write_bundle(self, resources: list) -> Path:
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [{"resource": r} for r in resources],
        }
        p = self.root / "portal_export.json"
        p.write_text(json.dumps(bundle))
        return p

    def test_no_resource_type_vanishes_without_a_trace(self):
        path = self._write_bundle(list(REALISTIC_BUNDLE_RESOURCES.values()))
        counts = import_fhir_file(self.root, "me", path)

        for rtype in REALISTIC_BUNDLE_RESOURCES:
            if rtype in _ADMINISTRATIVE_RESOURCE_TYPES:
                continue  # no clinical content — silently ignoring is fine
            if rtype in _HANDLED_TYPES:
                continue  # merged into the profile directly, checked below
            self.assertIn(
                f"skipped_{rtype}", counts,
                f"{rtype} vanished: neither merged nor reported as skipped",
            )

    def test_handled_types_are_actually_merged(self):
        path = self._write_bundle(list(REALISTIC_BUNDLE_RESOURCES.values()))
        counts = import_fhir_file(self.root, "me", path)
        self.assertEqual(counts.get("conditions"), 1)
        self.assertEqual(counts.get("medications"), 1)
        self.assertEqual(counts.get("allergies"), 1)
        self.assertEqual(counts.get("immunisations"), 1)
        self.assertEqual(counts.get("diagnostic_reports"), 1)

    def test_diagnostic_report_conclusion_persisted(self):
        path = self._write_bundle([REALISTIC_BUNDLE_RESOURCES["DiagnosticReport"]])
        import_fhir_file(self.root, "me", path)
        profile = load_profile(self.root, "me")
        reports = profile.get("diagnostic_reports", [])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["conclusion"], "No acute findings.")
        self.assertEqual(reports[0]["name"], "Chest X-ray")

    def test_administrative_types_produce_no_skipped_key(self):
        admin_only = [
            r for rtype, r in REALISTIC_BUNDLE_RESOURCES.items()
            if rtype in _ADMINISTRATIVE_RESOURCE_TYPES
        ]
        path = self._write_bundle(admin_only)
        counts = import_fhir_file(self.root, "me", path)
        skipped = {k: v for k, v in counts.items() if k.startswith("skipped_")}
        self.assertEqual(skipped, {}, f"administrative types were reported as skipped: {skipped}")

    def test_unknown_future_resource_type_is_reported_not_dropped(self):
        # A resource type FHIR adds later that this module has never seen at all.
        path = self._write_bundle([{"resourceType": "NutritionOrder", "status": "active"}])
        counts = import_fhir_file(self.root, "me", path)
        self.assertEqual(counts.get("skipped_NutritionOrder"), 1)

    def test_duplicate_diagnostic_report_not_duplicated(self):
        report = REALISTIC_BUNDLE_RESOURCES["DiagnosticReport"]
        path = self._write_bundle([report])
        import_fhir_file(self.root, "me", path)
        import_fhir_file(self.root, "me", path)
        profile = load_profile(self.root, "me")
        matches = [d for d in profile.get("diagnostic_reports", []) if d["name"] == "Chest X-ray"]
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()
