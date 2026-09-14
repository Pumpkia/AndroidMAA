from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clothing_memory import (
    DONE,
    JOB_EVO_HUA,
    JOB_EVO_RARE,
    JOB_FARM,
    NO_TRIES,
    ClothingLedger,
)


class ClothingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "clothing_memory.json"
        self.day = "2026-09-10"
        self.ledger = ClothingLedger(self.path, today=lambda: self.day)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_default_plan_farms_until_evolve(self):
        self.assertEqual(self.ledger.next_job(), JOB_FARM)
        self.assertIn("8-支3", self.ledger.recommend())
        self.ledger.set_have("NZ-001", 6)
        self.assertEqual(self.ledger.next_job(), JOB_EVO_HUA)
        self.ledger.apply_job_success(JOB_EVO_HUA)
        self.assertEqual(self.ledger.piece("NZ-001").have, 1)
        self.assertEqual(self.ledger.piece("NZ-002").have, 1)
        self.ledger.set_have("NZ-002", 5)
        self.assertEqual(self.ledger.next_job(), JOB_EVO_RARE)
        self.ledger.apply_job_success(JOB_EVO_RARE)
        self.assertEqual(self.ledger.piece("NZ-002").have, 1)
        self.assertEqual(self.ledger.piece("NZ-003").have, 1)
        self.assertEqual(self.ledger.next_job(), DONE)

    def test_farm_callback_writes_have_and_daily_remain(self):
        self.ledger.apply_job_success(JOB_FARM)
        self.assertEqual(self.ledger.piece("NZ-001").have, 1)
        self.assertEqual(self.ledger.daily["remain"], 2)
        loaded = ClothingLedger(self.path, today=lambda: self.day)
        self.assertEqual(loaded.piece("NZ-001").have, 1)
        self.assertEqual(loaded.daily["remain"], 2)
        self.ledger.apply_job_success(JOB_FARM)
        self.ledger.apply_job_success(JOB_FARM)
        with self.assertRaises(ValueError):
            self.ledger.apply_job_success(JOB_FARM)
        self.day = "2026-09-11"
        self.assertEqual(self.ledger.next_job(), JOB_FARM)
        self.assertEqual(self.ledger.daily["remain"], 3)

    def test_inventory_set_have_is_source_of_truth(self):
        self.ledger.set_have("NZ-001", 5)
        self.ledger.set_have("NZ-002", 1)
        self.ledger.set_have("NZ-003", 0)
        self.assertEqual(self.ledger.piece("NZ-001").consumable, 4)
        self.assertEqual(self.ledger.piece("NZ-002").consumable, 0)
        self.assertEqual(self.ledger.next_job(), JOB_FARM)

    def test_ocr_need_overrides_fallback(self):
        self.ledger.set_have("NZ-002", 3)
        self.assertNotEqual(self.ledger.next_job(), JOB_EVO_RARE)
        self.ledger.set_evolve_need("NZ-003", 2)
        self.assertEqual(self.ledger.next_job(), JOB_EVO_RARE)

    def test_malformed_file_is_reported(self):
        self.path.write_text(json.dumps({"format_version": 1, "items": []}), encoding="utf-8")
        loaded = ClothingLedger(self.path, today=lambda: self.day)
        self.assertTrue(loaded.load_error)
        self.assertEqual(loaded.chain, [])


if __name__ == "__main__":
    unittest.main()
