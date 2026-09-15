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

    def test_tree_lists_base_then_hua_then_rare(self):
        roots = self.ledger.roots()
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].name, "姹紫嫣红")
        hua = self.ledger.children_of(roots[0].id)
        self.assertEqual([item.name for item in hua], ["姹紫嫣红·华丽"])
        rare = self.ledger.children_of(hua[0].id)
        self.assertEqual([item.name for item in rare], ["姹紫嫣红·珍稀"])

    def test_add_item_uses_typed_name_only(self):
        path = Path(self.temporary_directory.name) / "blank.json"
        ledger = ClothingLedger(path, today=lambda: self.day)
        ledger.chain = []
        ledger.target = {"id": "", "name": "", "asset": ""}
        base = ledger.add_item("冰雪恋诗", stage="8-支3")
        self.assertEqual(base.name, "冰雪恋诗")
        self.assertEqual(ledger.piece(base.id).tier, "base")
        hua = ledger.add_item("冰雪恋诗·华丽", parent_id=base.id)
        self.assertEqual(hua.name, "冰雪恋诗·华丽")
        self.assertEqual(ledger.piece(hua.id).tier, "hua")
        rare = ledger.add_item("冰雪恋诗·珍稀", parent_id=hua.id)
        self.assertEqual(rare.name, "冰雪恋诗·珍稀")
        self.assertEqual(ledger.piece(rare.id).tier, "rare")
        with self.assertRaises(ValueError):
            ledger.add_item("", parent_id=base.id)

    def test_add_item_keeps_category_limit_and_independent_roots(self):
        path = Path(self.temporary_directory.name) / "custom.json"
        ledger = ClothingLedger(path, today=lambda: self.day)
        ledger.chain = []
        ledger.target = {"id": "", "name": "", "asset": ""}
        first = ledger.add_item("冰雪恋诗", category="连衣裙", needed=4, stage="8-支3", daily_limit=5)
        second = ledger.add_item("星之海", category="连衣裙", stage="8-支1", daily_limit=3)
        self.assertEqual(first.category, "连衣裙")
        self.assertEqual(first.needed, 4)
        self.assertEqual(first.daily_limit, 5)
        self.assertEqual([item.name for item in ledger.roots()], ["星之海", "冰雪恋诗"])
        loaded = ClothingLedger(path, today=lambda: self.day)
        stored = loaded.get(first.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.category, "连衣裙")
        self.assertEqual(stored.needed, 4)
        self.assertEqual(stored.daily_limit, 5)
        self.assertEqual(stored.parent_id, "")
        self.assertEqual(loaded.get(second.id).parent_id, "")
        child = loaded.add_item("冰雪恋诗·华丽", category="连衣裙", parent_id=first.id, needed=5)
        self.assertEqual(child.parent_id, first.id)
        self.assertEqual([item.name for item in loaded.children_of(first.id)], ["冰雪恋诗·华丽"])
        loaded.remove(first.id)
        self.assertEqual(loaded.get(child.id).parent_id, "")
        self.assertIn(child.id, [item.id for item in loaded.roots()])

    def test_malformed_file_is_reported(self):
        self.path.write_text(json.dumps({"format_version": 1, "items": []}), encoding="utf-8")
        loaded = ClothingLedger(self.path, today=lambda: self.day)
        self.assertTrue(loaded.load_error)
        self.assertEqual(loaded.chain, [])


if __name__ == "__main__":
    unittest.main()
