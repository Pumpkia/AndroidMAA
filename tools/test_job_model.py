import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_model import (
    JOB_FORMAT_VERSION, JobDocument, JobStep, safe_name, suggest_category,
)


class JobModelTests(unittest.TestCase):
    def test_semantic_steps_round_trip_and_export_ocr_pipeline(self):
        source = JobDocument(
            name="语义导航",
            steps=[
                JobStep(
                    name="点击搜索",
                    recognition="OCR",
                    action="Click",
                    expected="搜索",
                    roi=[36, 80, 144, 64],
                    target=[504, 80, 180, 64],
                    post_delay=700,
                    semantic_purpose="click",
                    roi_ratio=[.05, .05, .25, .09],
                    target_ratio=[.7, .05, .95, .09],
                ),
                JobStep(
                    name="检查结果",
                    recognition="OCR",
                    action="DoNothing",
                    expected="搜索结果",
                    roi=[36, 160, 360, 80],
                    post_delay=200,
                    semantic_purpose="check",
                    roi_ratio=[.05, .1, .55, .15],
                ),
                JobStep(
                    name="识别完成",
                    recognition="OCR",
                    action="DoNothing",
                    expected="完成",
                    roi=[36, 320, 180, 80],
                    post_delay=200,
                    semantic_purpose="recognize",
                    roi_ratio=[.05, .2, .3, .25],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "semantic.maa_job.json"
            source.save(path)
            loaded = JobDocument.load(path)
            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded, source)
        pipeline = loaded.to_pipeline()
        click = pipeline["点击搜索"]
        check = pipeline["检查结果"]
        recognize = pipeline["识别完成"]
        self.assertEqual(click["roi"], [36, 80, 144, 64])
        self.assertEqual(click["target"], [504, 80, 180, 64])
        self.assertEqual(click["action"], "Click")
        self.assertEqual(click["next"], ["检查结果"])
        self.assertEqual(check["action"], "DoNothing")
        self.assertEqual(check["next"], ["识别完成"])
        self.assertNotIn("target", check)
        self.assertEqual(recognize["action"], "DoNothing")
        self.assertEqual(recognize["next"], [])
        self.assertNotIn("semantic_purpose", click)
        for node in (click, check, recognize):
            self.assertNotIn("roi_ratio", node)
            self.assertNotIn("target_ratio", node)

        self.assertEqual(stored["format_version"], JOB_FORMAT_VERSION)
        self.assertEqual(stored["steps"][0]["roi_ratio"], [.05, .05, .25, .09])

    def test_runtime_materializes_semantic_ratios_for_different_aspect_ratio(self):
        document = JobDocument(
            name="aspect_ratio",
            device_size=[720, 1600],
            steps=[
                JobStep(
                    name="semantic_click",
                    recognition="OCR",
                    action="Click",
                    expected="Open",
                    roi=[0, 1280, 720, 160],
                    target=[72, 1280, 360, 160],
                    semantic_purpose="click",
                    roi_ratio=[0, .8, 1, .9],
                    target_ratio=[.1, .8, .6, .9],
                ),
                JobStep(
                    name="regular_click",
                    recognition="DirectHit",
                    action="Click",
                    target=[10, 20],
                ),
            ],
        )

        pipeline = document.to_pipeline(runtime_device_size=[720, 1280])

        semantic = pipeline["semantic_click"]
        self.assertEqual(semantic["roi"], [0, 1024, 720, 128])
        self.assertEqual(semantic["target"], [72, 1024, 360, 128])
        self.assertNotIn("roi_ratio", semantic)
        self.assertNotIn("target_ratio", semantic)
        self.assertEqual(pipeline["regular_click"]["target"], [10, 20])

    def test_legacy_v2_semantic_pixels_derive_runtime_ratios(self):
        payload = {
            "format_version": 2,
            "name": "legacy_semantic",
            "device_size": [720, 1600],
            "steps": [
                {
                    "name": "legacy_check",
                    "recognition": "OCR",
                    "action": "DoNothing",
                    "expected": "Ready",
                    "roi": [0, 1280, 720, 160],
                    "semantic_purpose": "check",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy-v2.maa_job.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            loaded = JobDocument.load(path)

        self.assertIsNone(loaded.steps[0].roi_ratio)
        pipeline = loaded.to_pipeline(runtime_device_size=[720, 1280])
        self.assertEqual(
            pipeline["legacy_check"]["roi"],
            [0, 1024, 720, 128],
        )

    def test_ratio_metadata_validation_rejects_malformed_bounds(self):
        step = JobStep(
            name="bad_ratio",
            recognition="OCR",
            action="DoNothing",
            expected="Ready",
            roi=[0, 0, 100, 100],
            semantic_purpose="check",
            roi_ratio=[0.8, 0.1, 0.2, 0.3],
        )

        self.assertTrue(any("roi_ratio" in error for error in step.validate()))

    def test_semantic_validation_reports_purpose_and_shape_errors(self):
        invalid = JobStep(
            name="错误语义步骤",
            recognition="DirectHit",
            action="Click",
            roi=[10, 20, 0, 40],
            target=[100, 200],
            semantic_purpose="click",
        )
        errors = "\n".join(invalid.validate())
        self.assertIn("语义步骤必须使用 OCR 识别", errors)
        self.assertIn("[x, y, 宽, 高] 格式的识别区域", errors)
        self.assertIn("[x, y, 宽, 高] 格式的点击区域", errors)

        unsupported = JobStep(name="错误用途", semantic_purpose="tap")
        self.assertIn("不支持的语义用途: tap", "\n".join(unsupported.validate()))

        mismatched = JobStep(
            name="错误检查",
            recognition="OCR",
            action="Click",
            expected="已完成",
            roi=[0, 0, 100, 40],
            target=[0, 0, 100, 40],
            semantic_purpose="check",
        )
        self.assertIn("check 语义用途必须使用 DoNothing 动作", "\n".join(mismatched.validate()))

    def test_loads_legacy_v1_and_v2_steps_without_semantic_purpose(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / f"v{version}.maa_job.json"
                path.write_text(
                    json.dumps(
                        {
                            "format_version": version,
                            "name": f"旧版 v{version}",
                            "steps": [
                                {
                                    "name": "返回",
                                    "recognition": "DirectHit",
                                    "action": "ClickKey",
                                    "key": 4,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                loaded = JobDocument.load(path)

                self.assertEqual(loaded.steps[0].semantic_purpose, "")
                self.assertEqual(loaded.validate(), [])

    def test_rejects_malformed_job_container_types(self):
        cases = (
            ([], "作业文件顶层必须是对象"),
            ({"format_version": 1, "steps": {}}, "steps 必须是数组"),
            ({"format_version": 1, "prerequisites": {"job": 1}}, "prerequisites 必须是字符串数组"),
            ({"format_version": 1, "steps": [None]}, "步骤定义必须是对象"),
        )
        for payload, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "malformed.maa_job.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    JobDocument.load(path)

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
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format_version"], JOB_FORMAT_VERSION)

    def test_round_trip_job_file_with_module_binding(self):
        source = JobDocument(
            name="semantic flow",
            category="automation",
            module_id="semantic",
            module_version=3,
            steps=[
                JobStep(
                    name="check ready",
                    recognition="OCR",
                    action="DoNothing",
                    expected="Ready",
                    roi=[0, 0, 100, 40],
                    semantic_purpose="check",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bound.maa_job.json"
            source.save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded = JobDocument.load(path)

        self.assertEqual(loaded, source)
        self.assertEqual(payload["module_id"], "semantic")
        self.assertEqual(payload["module_version"], 3)

    def test_legacy_job_without_module_binding_defaults_to_unbound(self):
        payload = {
            "format_version": 1,
            "name": "legacy",
            "category": "default",
            "steps": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.maa_job.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = JobDocument.load(path)

        self.assertEqual(loaded.module_id, "")
        self.assertEqual(loaded.module_version, 1)
        self.assertEqual(loaded.validate(), [])

    def test_module_binding_validation_rejects_invalid_values(self):
        invalid_id = JobDocument(module_id="Bad ID")
        self.assertTrue(any("模块 ID" in error for error in invalid_id.validate()))

        invalid_type = JobDocument(module_id={"id": "semantic"})
        self.assertTrue(any("模块 ID" in error for error in invalid_type.validate()))

        invalid_version = JobDocument(module_id="semantic", module_version=0)
        self.assertTrue(any("模块版本" in error for error in invalid_version.validate()))

        bool_version = JobDocument(module_id="semantic", module_version=True)
        self.assertTrue(any("模块版本" in error for error in bool_version.validate()))
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
