import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_model import JobDocument, JobStep, safe_name, suggest_category, suggest_category


class JobModelTests(unittest.TestCase):
    def test_exports_linear_template_and_input_pipeline(self):
        document = JobDocument(
            name="QQ 登录演示",
            steps=[
                JobStep(
                    name="点击登录",
                    recognition="TemplateMatch",
                    action="Click",
                    template="jobs/qq_login/click_login.png",
                    roi=[20, 40, 300, 180],
                    pre_delay=250,
                ),
                JobStep(
                    name="输入账号",
                    recognition="DirectHit",
                    action="InputText",
                    input_text="123456",
                ),
            ],
        )

        pipeline = document.to_pipeline()

        self.assertEqual(pipeline["QQ_登录演示"]["next"], ["点击登录"])
        self.assertEqual(pipeline["点击登录"]["template"], "jobs/qq_login/click_login.png")
        self.assertEqual(pipeline["点击登录"]["pre_delay"], 250)
        self.assertNotIn("target", pipeline["点击登录"])
        self.assertEqual(pipeline["点击登录"]["next"], ["输入账号"])
        self.assertEqual(pipeline["输入账号"]["input_text"], "123456")
        self.assertEqual(pipeline["输入账号"]["next"], [])

    def test_round_trip_job_file_with_category_and_prerequisite(self):
        source = JobDocument(
            name="测试",
            category="账号",
            prerequisites=["启动/打开QQ.maa_job.json"],
            steps=[JobStep(name="返回", recognition="DirectHit", action="ClickKey", key=4)],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "job.json"
            source.save(path)
            loaded = JobDocument.load(path)
            self.assertEqual(loaded, source)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format_version"], 2)

    def test_prerequisites_are_composed_before_current_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            prerequisite_path = jobs_dir / "基础" / "打开QQ.maa_job.json"
            JobDocument(
                name="打开QQ",
                category="基础",
                steps=[JobStep(name="返回桌面", recognition="DirectHit", action="ClickKey", key=3)],
            ).save(prerequisite_path)
            current = JobDocument(
                name="输入账号",
                category="登录",
                prerequisites=["基础/打开QQ.maa_job.json"],
                steps=[JobStep(name="输入", recognition="DirectHit", action="InputText", input_text="123")],
            )

            pipeline = current.to_pipeline(current.resolve_prerequisites(jobs_dir))

            self.assertEqual(pipeline["输入账号"]["next"], ["打开QQ__返回桌面"])
            self.assertEqual(pipeline["打开QQ__返回桌面"]["next"], ["输入"])
            self.assertEqual(pipeline["输入"]["input_text"], "123")

    def test_cycle_in_prerequisites_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir)
            JobDocument(name="A", prerequisites=["b.maa_job.json"]).save(jobs_dir / "a.maa_job.json")
            JobDocument(name="B", prerequisites=["a.maa_job.json"]).save(jobs_dir / "b.maa_job.json")
            current = JobDocument(name="Current", prerequisites=["a.maa_job.json"])
            with self.assertRaisesRegex(ValueError, "循环依赖"):
                current.resolve_prerequisites(jobs_dir)

    def test_validation_rejects_incomplete_steps(self):
        document = JobDocument(steps=[JobStep(name="点击", recognition="DirectHit", action="Click")])
        self.assertIn("直接点击步骤必须选择点击坐标", "\n".join(document.validate()))

    def test_safe_name(self):
        self.assertEqual(safe_name(" QQ 登录 / demo "), "QQ_登录_demo")


    def test_suggest_category_uses_job_content(self):
        self.assertEqual(suggest_category("QQ 登录", []), "账号与登录")
        self.assertEqual(
            suggest_category("资料", [JobStep(name="输入昵称", action="InputText", input_text="小明")]),
            "表单输入",
        )
        self.assertEqual(suggest_category("每日签到", []), "通用流程")


if __name__ == "__main__":
    unittest.main()
