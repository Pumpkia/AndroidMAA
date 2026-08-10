from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).resolve().parent.parent


class EntrypointContractTests(unittest.TestCase):
    def test_source_launcher_uses_active_qt_workbench(self):
        launcher = (PROJECT_DIR / "job-editor.bat").read_text(encoding="utf-8")
        self.assertIn(r"python tools\qt_workbench.py", launcher)
        self.assertNotIn(r"python tools\job_editor.py", launcher)

    def test_packaged_launcher_uses_active_qt_workbench(self):
        spec = (PROJECT_DIR / "Qdd.spec").read_text(encoding="utf-8")
        self.assertIn(r"tools\\qt_workbench.py", spec)
        self.assertIn("'semantic_navigator'", spec)
        self.assertIn("name='Qdd'", spec)
        self.assertIn(r"assets\\icons\\qdd.ico", spec)

    def test_qdd_icons_are_bundled(self):
        icon_dir = PROJECT_DIR / "assets" / "icons"
        self.assertTrue((icon_dir / "qdd-icon.png").is_file())
        self.assertTrue((icon_dir / "qdd.ico").is_file())

    def test_release_archive_stays_blank_before_local_data_is_restored(self):
        script = (PROJECT_DIR / "tools" / "build_release.ps1").read_text(encoding="utf-8")
        archive_position = script.index("Compress-Archive -Path $stagedAppPath")
        restore_position = script.index(
            "Copy-RuntimeData -ExistingAppPath $canonicalAppPath -NewAppPath $stagedAppPath"
        )
        replace_position = script.index(
            "Move-Item -LiteralPath $canonicalAppPath -Destination $backupAppPath"
        )

        self.assertLess(archive_position, restore_position)
        self.assertLess(restore_position, replace_position)
        self.assertIn(
            'New-Item -ItemType Directory -Path (Join-Path $stagedAppPath "jobs")',
            script,
        )
        self.assertNotIn(
            'Copy-Item -LiteralPath (Join-Path $projectRoot "jobs") -Destination $stagedAppPath',
            script,
        )

    def test_release_restore_preserves_jobs_and_referenced_templates(self):
        script = (PROJECT_DIR / "tools" / "build_release.ps1").read_text(encoding="utf-8")

        self.assertIn("function Copy-FileTree", script)
        self.assertIn("function Copy-RuntimeData", script)
        self.assertIn(
            'Copy-FileTree -SourceRoot $existingJobs -DestinationRoot (Join-Path $NewAppPath "jobs")',
            script,
        )
        self.assertIn('-Filter "*.maa_job.json"', script)
        self.assertIn("foreach ($step in @($job.steps))", script)
        self.assertIn("$sourceTemplate.StartsWith($resolvedImageRoot", script)
        self.assertIn(
            "Copy-Item -LiteralPath $sourceTemplate -Destination $destinationTemplate",
            script,
        )

    def test_modified_text_files_do_not_start_with_utf8_bom(self):
        paths = (
            PROJECT_DIR / "README.md",
            PROJECT_DIR / "tools" / "build_release.ps1",
            PROJECT_DIR / "tools" / "semantic_navigator.py",
            PROJECT_DIR / "tools" / "test_entrypoints.py",
            PROJECT_DIR / "tools" / "test_qt_workbench.py",
            PROJECT_DIR / "\u754c\u9762\u529f\u80fd\u8bf4\u660e.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

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
