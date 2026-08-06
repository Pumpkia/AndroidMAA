from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).resolve().parent.parent


class EntrypointContractTests(unittest.TestCase):
    def test_source_launcher_uses_active_qt_workbench(self):
        launcher = (PROJECT_DIR / "job-editor.bat").read_text(encoding="utf-8")
        self.assertIn(r"python tools\qt_workbench.py", launcher)
        self.assertNotIn(r"python tools\job_editor.py", launcher)

    def test_packaged_launcher_uses_active_qt_workbench(self):
        spec = (PROJECT_DIR / "QQJobEditor.spec").read_text(encoding="utf-8")
        self.assertIn(r"tools\\qt_workbench.py", spec)
        self.assertIn("'semantic_navigator'", spec)

    def test_schema_validator_uses_bundled_maa_schemas(self):
        from validate_schema import DEFAULT_SCHEMA_DIR

        self.assertTrue((DEFAULT_SCHEMA_DIR / "pipeline.schema.json").is_file())
        self.assertTrue((DEFAULT_SCHEMA_DIR / "interface.schema.json").is_file())

    def test_login_pipeline_targets_android_qq_package(self):
        pipeline = (PROJECT_DIR / "assets" / "resource" / "pipeline" / "login.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"package": "com.tencent.mobileqq"', pipeline)
        self.assertNotIn('"package": "com.tencent.qq"', pipeline)

if __name__ == "__main__":
    unittest.main()
