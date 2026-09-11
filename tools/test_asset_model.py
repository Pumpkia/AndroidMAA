from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_model import ASSET_CATEGORIES, AssetLibrary
from job_model import JobDocument, JobStep


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "assets"
        self.library = AssetLibrary(self.root)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_import_lists_and_relative_template_path(self):
        source = Path(self.temporary_directory.name) / "hair.png"
        source.write_bytes(PNG)
        asset = self.library.import_file(source, "发型", "星光卷发")
        self.assertEqual(asset.category, "发型")
        self.assertEqual(asset.relative, "assets/发型/星光卷发.png")
        self.assertTrue(asset.path.is_file())
        listed = self.library.list_assets("发型")
        self.assertEqual([item.relative for item in listed], [asset.relative])
        self.assertIn("发型", self.library.list_categories())
        self.assertEqual(ASSET_CATEGORIES[0], "发型")

    def test_rejects_non_image_import(self):
        source = Path(self.temporary_directory.name) / "notes.txt"
        source.write_text("nope", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.library.import_file(source, "主界面")

    def test_finds_job_references_and_delete(self):
        source = Path(self.temporary_directory.name) / "home.png"
        source.write_bytes(PNG)
        asset = self.library.import_file(source, "主界面", "大厅")
        jobs_dir = Path(self.temporary_directory.name) / "jobs"
        JobDocument(
            name="回到大厅",
            category="登录与大厅",
            module_id="assets",
            steps=[
                JobStep(
                    name="大厅",
                    recognition="TemplateMatch",
                    action="Click",
                    template=asset.relative,
                    roi=[0, 0, 10, 10],
                    target=[1, 2],
                )
            ],
        ).save(jobs_dir / "登录与大厅" / "home.maa_job.json")
        self.assertEqual(self.library.find_references(jobs_dir, asset.relative), [
            jobs_dir / "登录与大厅" / "home.maa_job.json"
        ])
        self.library.delete(asset)
        self.assertFalse(asset.path.exists())
        self.assertEqual(self.library.list_assets("主界面"), [])


if __name__ == "__main__":
    unittest.main()
