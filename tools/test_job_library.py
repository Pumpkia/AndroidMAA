from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_library import JOB_FILE_SUFFIX, JobLibrary
from job_model import JobDocument, JobStep


class JobLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "作业"
        self.library = JobLibrary(self.root)
        self.root = self.library.root

    def tearDown(self):
        self.temporary_directory.cleanup()

    def save_job(
        self,
        relative_path: str,
        *,
        name: str = "奇迹暖暖作业",
        category: str = "默认",
        prerequisites: list[str] | None = None,
    ) -> Path:
        path = self.root / relative_path
        JobDocument(
            name=name,
            category=category,
            prerequisites=prerequisites or [],
            steps=[JobStep(name="返回", recognition="DirectHit", action="ClickKey")],
        ).save(path)
        return path

    def test_lists_empty_and_populated_categories(self):
        self.library.create_category("空分类")
        self.library.create_category("通用流程")
        self.save_job(f"通用流程/奇迹暖暖作业{JOB_FILE_SUFFIX}", category="通用流程")

        categories = self.library.list_categories()

        self.assertEqual([item.name for item in categories], ["空分类", "通用流程"])
        self.assertEqual([item.job_count for item in categories], [0, 1])
        self.assertTrue(all(item.path.is_absolute() for item in categories))

    def test_create_category_rejects_duplicates_and_unsafe_names(self):
        created = self.library.create_category("我的 分类")
        self.assertEqual(created.name, "我的 分类")
        with self.assertRaises(FileExistsError):
            self.library.create_category("我的 分类")
        for name in ("", " ../越界", "../越界", "a/b", "a\\b", "CON", "分类."):
            with self.subTest(name=name), self.assertRaises((ValueError, FileExistsError)):
                self.library.create_category(name)

    def test_rename_category_updates_all_job_documents(self):
        self.library.create_category("旧分类")
        first = self.save_job(f"旧分类/作业一{JOB_FILE_SUFFIX}", name="作业一", category="错误旧值")
        second = self.save_job(f"旧分类/子目录/作业二{JOB_FILE_SUFFIX}", name="作业二", category="旧分类")

        result = self.library.rename_category("旧分类", "新分类")

        self.assertEqual(result.path, (self.root / "新分类").resolve())
        self.assertEqual(result.jobs_updated, 2)
        self.assertFalse(first.exists())
        self.assertEqual(JobDocument.load(result.path / first.name).category, "新分类")
        self.assertEqual(JobDocument.load(result.path / "子目录" / second.name).category, "新分类")

    def test_rename_category_never_overwrites_existing_category(self):
        old_path = self.library.create_category("旧分类")
        new_path = self.library.create_category("新分类")
        with self.assertRaises(FileExistsError):
            self.library.rename_category("旧分类", "新分类")
        self.assertTrue(old_path.exists())
        self.assertTrue(new_path.exists())

    def test_delete_category_returns_statistics_and_removes_everything(self):
        category = self.library.create_category("待删除")
        self.save_job(f"待删除/作业{JOB_FILE_SUFFIX}", category="待删除")
        (category / "图片").mkdir()
        (category / "图片" / "模板.png").write_bytes(b"image")

        result = self.library.delete_category("待删除")

        self.assertEqual(result.path, category)
        self.assertEqual(result.jobs_deleted, 1)
        self.assertEqual(result.files_deleted, 2)
        self.assertEqual(result.directories_deleted, 2)
        self.assertFalse(category.exists())

    def test_delete_job_rejects_paths_outside_the_library(self):
        job = self.save_job(f"默认/作业{JOB_FILE_SUFFIX}")
        deleted = self.library.delete_job(job)
        self.assertEqual(deleted, job.resolve())
        self.assertFalse(job.exists())

        outside = Path(self.temporary_directory.name) / f"外部{JOB_FILE_SUFFIX}"
        JobDocument(name="外部").save(outside)
        with self.assertRaisesRegex(ValueError, "路径越界"):
            self.library.delete_job(outside)
        self.assertTrue(outside.exists())

    def test_move_job_updates_category_and_uses_unique_safe_filename(self):
        self.library.create_category("来源")
        target = self.library.create_category("目标 分类")
        source = self.save_job(f"来源/QQ 作业{JOB_FILE_SUFFIX}", name="QQ 作业", category="来源")
        existing = self.save_job(f"目标 分类/QQ_作业{JOB_FILE_SUFFIX}", name="已有", category="目标 分类")

        destination = self.library.move_job(source, "目标 分类")

        self.assertEqual(destination, target / f"QQ_作业_2{JOB_FILE_SUFFIX}")
        self.assertFalse(source.exists())
        self.assertTrue(existing.exists())
        moved = JobDocument.load(destination)
        self.assertEqual(moved.name, "QQ 作业")
        self.assertEqual(moved.category, "目标 分类")

    def test_move_job_to_same_category_repairs_category_field(self):
        self.library.create_category("通用流程")
        source = self.save_job(f"通用流程/作业{JOB_FILE_SUFFIX}", category="旧值")

        destination = self.library.move_job(source, "通用流程")

        self.assertEqual(destination, source.resolve())
        self.assertEqual(JobDocument.load(source).category, "通用流程")

    def test_move_job_requires_an_existing_target_category(self):
        source = self.save_job(f"默认/作业{JOB_FILE_SUFFIX}")
        with self.assertRaises(FileNotFoundError):
            self.library.move_job(source, "不存在")
        self.assertTrue(source.exists())


    def test_lists_document_defined_category_without_directory(self):
        self.save_job(f"根目录作业{JOB_FILE_SUFFIX}", category="自定义分类")

        categories = {item.name: item for item in self.library.list_categories()}

        self.assertEqual(categories["自定义分类"].job_count, 1)
        self.assertEqual(categories["自定义分类"].path, (self.root / "自定义分类").resolve())
        self.assertFalse(categories["自定义分类"].path.exists())

    def test_rename_category_moves_legacy_root_jobs_and_repairs_prerequisites(self):
        self.library.create_category("旧分类")
        self.library.create_category("依赖")
        nested = self.save_job(f"旧分类/目录作业{JOB_FILE_SUFFIX}", category="旧分类")
        legacy = self.save_job(f"根目录作业{JOB_FILE_SUFFIX}", category="旧分类")
        old_references = [
            nested.relative_to(self.root).as_posix(),
            legacy.relative_to(self.root).as_posix(),
        ]
        dependent = self.save_job(
            f"依赖/组合{JOB_FILE_SUFFIX}",
            category="依赖",
            prerequisites=old_references,
        )

        result = self.library.rename_category("旧分类", "新分类")
        moved = dict(result.moved_jobs)

        self.assertEqual(result.jobs_updated, 2)
        self.assertFalse(nested.exists())
        self.assertFalse(legacy.exists())
        self.assertEqual(JobDocument.load(moved[nested.resolve(strict=False)]).category, "新分类")
        self.assertEqual(JobDocument.load(moved[legacy.resolve(strict=False)]).category, "新分类")
        expected_references = [
            moved[nested.resolve(strict=False)].relative_to(self.root).as_posix(),
            moved[legacy.resolve(strict=False)].relative_to(self.root).as_posix(),
        ]
        self.assertEqual(JobDocument.load(dependent).prerequisites, expected_references)

    def test_move_job_repairs_prerequisite_references(self):
        self.library.create_category("来源")
        self.library.create_category("目标")
        self.library.create_category("依赖")
        source = self.save_job(f"来源/作业{JOB_FILE_SUFFIX}", category="来源")
        dependent = self.save_job(
            f"依赖/组合{JOB_FILE_SUFFIX}",
            category="依赖",
            prerequisites=[source.relative_to(self.root).as_posix()],
        )

        destination = self.library.move_job(source, "目标")

        self.assertEqual(
            JobDocument.load(dependent).prerequisites,
            [destination.relative_to(self.root).as_posix()],
        )

    def test_find_by_name_matches_file_stem_and_safe_name(self):
        self.library.create_category("仓库")
        path = self.save_job(
            f"仓库/farm_8z3_once{JOB_FILE_SUFFIX}",
            name="每日刷关",
            category="仓库",
        )
        self.assertEqual(self.library.find_by_name("farm_8z3_once"), path)
        self.assertEqual(self.library.find_by_name("每日刷关"), path)
        self.assertEqual(self.library.find_by_name(" 每日刷关 "), path)

    def test_delete_job_removes_prerequisite_references(self):
        self.library.create_category("来源")
        self.library.create_category("依赖")
        source = self.save_job(f"来源/作业{JOB_FILE_SUFFIX}", category="来源")
        dependent = self.save_job(
            f"依赖/组合{JOB_FILE_SUFFIX}",
            category="依赖",
            prerequisites=[source.relative_to(self.root).as_posix()],
        )

        self.library.delete_job(source)

        self.assertEqual(JobDocument.load(dependent).prerequisites, [])

    def test_delete_category_removes_physical_and_legacy_jobs(self):
        self.library.create_category("待删除")
        self.library.create_category("依赖")
        nested = self.save_job(f"待删除/目录作业{JOB_FILE_SUFFIX}", category="待删除")
        legacy = self.save_job(f"根目录作业{JOB_FILE_SUFFIX}", category="待删除")
        dependent = self.save_job(
            f"依赖/组合{JOB_FILE_SUFFIX}",
            category="依赖",
            prerequisites=[
                nested.relative_to(self.root).as_posix(),
                legacy.relative_to(self.root).as_posix(),
            ],
        )

        result = self.library.delete_category("待删除")

        self.assertEqual(result.jobs_deleted, 2)
        self.assertFalse(nested.exists())
        self.assertFalse(legacy.exists())
        self.assertEqual(JobDocument.load(dependent).prerequisites, [])


if __name__ == "__main__":
    unittest.main()
