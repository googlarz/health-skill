"""Garmin Connect activities-export importer."""

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.care_workspace import ensure_person, load_profile
from scripts.wearable_import import (
    _normalize_garmin_type,
    _parse_garmin_duration_min,
    import_wearable_file,
    is_garmin_activities_csv,
)

GARMIN_HEADER = "Activity Type,Date,Title,Distance,Calories,Time,Avg HR,Max HR\n"


class GarminDetectionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write(self, content: str, name: str = "Activities.csv") -> Path:
        p = self.root / name
        p.write_text(content)
        return p

    def test_garmin_header_detected(self):
        path = self._write(GARMIN_HEADER + '"Running","2025-06-01 07:00:00","Morning Run","5.02","320","28:15","152","168"\n')
        self.assertTrue(is_garmin_activities_csv(path))

    def test_generic_csv_not_detected_as_garmin(self):
        path = self._write("date,metric,value,unit\n2025-06-01,heart_rate,58,bpm\n")
        self.assertFalse(is_garmin_activities_csv(path))


class GarminTypeNormalizationTests(unittest.TestCase):
    def test_running_variants_map_to_run(self):
        for label in ("Running", "Treadmill Running", "Trail Running", "track running"):
            self.assertEqual(_normalize_garmin_type(label), "run")

    def test_cycling_variants_map_to_cycling(self):
        for label in ("Cycling", "Road Cycling", "Mountain Biking"):
            self.assertEqual(_normalize_garmin_type(label), "cycling")

    def test_unknown_type_falls_back_not_dropped(self):
        self.assertEqual(_normalize_garmin_type("Stand Up Paddleboarding"), "stand_up_paddleboarding")

    def test_empty_type_is_other(self):
        self.assertEqual(_normalize_garmin_type(""), "other")


class GarminDurationParsingTests(unittest.TestCase):
    def test_hms_format(self):
        self.assertAlmostEqual(_parse_garmin_duration_min("1:02:30"), 62.5)

    def test_ms_format(self):
        self.assertAlmostEqual(_parse_garmin_duration_min("28:15"), 28.25)

    def test_dashes_return_none(self):
        self.assertIsNone(_parse_garmin_duration_min("--"))

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_garmin_duration_min("not a time"))


class GarminImportEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_person(self.root, "me", "Test", "1985-01-01", "female")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write(self, rows: str) -> Path:
        p = self.root / "Activities.csv"
        p.write_text(GARMIN_HEADER + rows)
        return p

    def test_run_imported_with_pace_computable(self):
        path = self._write('"Running","2025-06-01 07:00:00","Morning Run","5.00","320","25:00","152","168"\n')
        counts = import_wearable_file(self.root, "me", path)
        self.assertEqual(counts.get("run"), 1)
        profile = load_profile(self.root, "me")
        runs = [w for w in profile["workouts"] if w["type"] == "run"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["distance_km"], 5.0)
        self.assertEqual(runs[0]["duration_min"], 25.0)
        self.assertEqual(runs[0]["hr_avg"], 152.0)
        self.assertEqual(runs[0]["source"]["label"], "Garmin Connect")

    def test_miles_converted_to_km(self):
        path = self._write('"Running","2025-06-01 07:00:00","Morning Run","3.11","300","25:00","150","165"\n')
        import_wearable_file(self.root, "me", path, distance_unit="mi")
        profile = load_profile(self.root, "me")
        runs = [w for w in profile["workouts"] if w["type"] == "run"]
        self.assertAlmostEqual(runs[0]["distance_km"], 3.11 * 1.60934, places=2)

    def test_strength_activity_without_distance_does_not_crash(self):
        path = self._write('"Strength Training","2025-06-02 18:00:00","Gym","--","250","45:00","--","--"\n')
        counts = import_wearable_file(self.root, "me", path)
        self.assertEqual(counts.get("strength"), 1)
        profile = load_profile(self.root, "me")
        strength = [w for w in profile["workouts"] if w["type"] == "strength"]
        self.assertNotIn("distance_km", strength[0])
        self.assertNotIn("hr_avg", strength[0])

    def test_reimport_does_not_duplicate(self):
        path = self._write('"Running","2025-06-01 07:00:00","Morning Run","5.00","320","25:00","152","168"\n')
        import_wearable_file(self.root, "me", path)
        import_wearable_file(self.root, "me", path)
        profile = load_profile(self.root, "me")
        runs = [w for w in profile["workouts"] if w["type"] == "run" and w["date"] == "2025-06-01"]
        self.assertEqual(len(runs), 1)

    def test_multiple_activities_counted_by_type(self):
        path = self._write(
            '"Running","2025-06-01 07:00:00","Run","5.00","320","25:00","152","168"\n'
            '"Cycling","2025-06-02 07:00:00","Ride","20.00","500","55:00","140","160"\n'
        )
        counts = import_wearable_file(self.root, "me", path)
        self.assertEqual(counts.get("run"), 1)
        self.assertEqual(counts.get("cycling"), 1)

    def test_generic_csv_still_works_unaffected(self):
        # Regression guard: adding Garmin detection must not break the existing
        # generic date/metric/value CSV import path.
        p = self.root / "vitals.csv"
        p.write_text("date,metric,value,unit\n2025-06-01,heart_rate,58,bpm\n")
        counts = import_wearable_file(self.root, "me", p)
        self.assertEqual(counts.get("heart_rate"), 1)


if __name__ == "__main__":
    unittest.main()
