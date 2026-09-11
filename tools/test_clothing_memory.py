from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clothing_memory import ClothingItem, ClothingLedger


class ClothingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "clothing_memory.json"
        self.day = "2026-09-10"
        self.ledger = ClothingLedger(self.path, today=lambda: self.day)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_hierarchy_missing_and_material_priority(self):
        target = self.ledger.add_item("星之海", category="连衣裙", needed=1, owned=0)
        material = self.ledger.add_item(
            "星之海·粉",
            category="连衣裙",
            needed=4,
            owned=1,
            stage="少女12-9",
            daily_limit=3,
            parent_id=target.id,
        )
        base = self.ledger.add_item(
            "星之纱",
            needed=8,
            owned=2,
            stage="少女5-3",
            daily_limit=3,
            parent_id=material.id,
        )
        self.assertEqual(target.missing, 1)
        self.assertEqual(material.missing, 3)
        self.assertEqual(self.ledger.layer_label(target.id), "目标")
        self.assertEqual(self.ledger.layer_label(base.id), "2级材料")
        queue = self.ledger.farm_queue()
        self.assertEqual([item.name for item, _missing, _left in queue], ["星之纱", "星之海·粉"])
        self.assertIn("少女5-3", self.ledger.recommend())

    def test_daily_clear_limit_resets_next_day(self):
        item = self.ledger.add_item("冰之谛", stage="少女4-12", needed=3, owned=0, daily_limit=3)
        self.assertEqual(self.ledger.record_clear(item.stage), 2)
        self.assertEqual(self.ledger.record_clear(item.stage), 1)
        self.assertEqual(self.ledger.record_clear(item.stage), 0)
        with self.assertRaises(ValueError):
            self.ledger.record_clear(item.stage)
        self.day = "2026-09-11"
        self.assertEqual(self.ledger.remaining(item.stage), 3)
        self.assertEqual(self.ledger.record_clear(item.stage), 2)

    def test_round_trip_and_remove_descendants(self):
        root = self.ledger.add_item("夜的咏叹调", needed=1)
        child = self.ledger.add_item("夜的咏叹调·珍稀", needed=3, parent_id=root.id, stage="少女10-2")
        self.ledger.add_item("夜的咏叹调·华丽", needed=4, parent_id=child.id)
        loaded = ClothingLedger(self.path, today=lambda: self.day)
        self.assertEqual(len(loaded.items), 3)
        self.assertEqual(loaded.get(child.id).stage, "少女10-2")
        loaded.remove(child.id)
        self.assertEqual([item.name for item in loaded.items], ["夜的咏叹调"])

    def test_gain_and_reject_cycle(self):
        parent = self.ledger.add_item("天鹅座", needed=1)
        child = self.ledger.add_item("天鹅绒", needed=2, parent_id=parent.id)
        updated = self.ledger.gain(child.id, 2)
        self.assertEqual(updated.owned, 2)
        self.assertEqual(updated.missing, 0)
        with self.assertRaises(ValueError):
            self.ledger.upsert(
                ClothingItem(id=parent.id, name="天鹅座", parent_id=child.id)
            )

    def test_malformed_file_is_reported(self):
        self.path.write_text(json.dumps({"format_version": 1, "items": "bad"}), encoding="utf-8")
        loaded = ClothingLedger(self.path, today=lambda: self.day)
        self.assertTrue(loaded.load_error)
        self.assertEqual(loaded.items, [])


if __name__ == "__main__":
    unittest.main()
