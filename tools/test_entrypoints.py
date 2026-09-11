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
        self.assertIn("'asset_page'", spec)
        self.assertIn("'clothing_memory'", spec)
        self.assertIn("'stage_navigator'", spec)
        self.assertIn("name='Qdd'", spec)
        self.assertIn(r"assets\\icons\\qdd.ico", spec)

    def test_qdd_icons_are_bundled(self):
        icon_dir = PROJECT_DIR / "assets" / "icons"
        self.assertTrue((icon_dir / "qdd-icon.png").is_file())
        self.assertTrue((icon_dir / "qdd.ico").is_file())
        self.assertTrue((icon_dir / "qdd.icns").is_file())

    def test_windows_release_branding(self):
        legacy_name = "QQ" + "JobEditor"
        windows_spec = (PROJECT_DIR / "Qdd.spec").read_text(encoding="utf-8")
        workflow = (
            PROJECT_DIR / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")

        self.assertFalse(
            (PROJECT_DIR / f"{legacy_name}.macos.spec").exists()
        )
        self.assertIn("name='Qdd'", windows_spec)
        self.assertIn("qdd.ico", windows_spec)
        self.assertIn("name: Qdd-${{ env.VERSION }}-win-x64", workflow)
        self.assertNotIn("macos-latest", workflow)
        self.assertNotIn("build_release_macos.py", workflow)
        self.assertNotIn("Qdd-${{ env.VERSION }}-macos", workflow)
        self.assertNotIn("release/*.dmg", workflow)
        self.assertNotIn("### macOS v2.1.0", readme)
        self.assertNotIn("Qdd-v2.1.0-macos-arm64.zip", readme)
        self.assertNotIn("Qdd-v2.1.0-macos-arm64.dmg", readme)
        self.assertNotIn("macOS 13", readme)

        for label, contents in (
            ("Windows spec", windows_spec),
            ("release workflow", workflow),
            ("README", readme),
        ):
            with self.subTest(label=label):
                self.assertNotIn(legacy_name, contents)

    def test_release_archive_stays_blank_before_local_data_is_restored(self):
        script = (PROJECT_DIR / "tools" / "build_release.ps1").read_text(encoding="utf-8")
        portable_create = "New-Item -ItemType File -Path $portableFlagPath"
        jobs_cleanup = script.index(
            "Remove-Item -LiteralPath $stagedJobsPath -Recurse -Force"
        )
        images_cleanup = script.index(
            "Remove-Item -LiteralPath $recordedImagePath -Recurse -Force"
        )
        first_portable_position = script.index(portable_create)
        archive_position = script.index("Compress-Archive -Path $stagedAppPath")
        portable_remove_position = script.index(
            "Remove-Item -LiteralPath $portableFlagPath -Force"
        )
        installer_position = script.index("& $resolvedIsccPath @isccArguments")
        second_portable_position = script.index(
            portable_create, first_portable_position + len(portable_create)
        )
        restore_position = script.index(
            "Copy-RuntimeData -ExistingAppPath $canonicalAppPath -NewAppPath $stagedAppPath"
        )
        replace_position = script.index(
            "Move-Item -LiteralPath $canonicalAppPath -Destination $backupAppPath"
        )

        self.assertLess(jobs_cleanup, first_portable_position)
        self.assertLess(images_cleanup, first_portable_position)
        self.assertLess(first_portable_position, archive_position)
        self.assertLess(archive_position, portable_remove_position)
        self.assertLess(portable_remove_position, installer_position)
        self.assertLess(installer_position, second_portable_position)
        self.assertLess(second_portable_position, restore_position)
        self.assertLess(restore_position, replace_position)
        self.assertIn('$setupPath = Join-Path $releasePath "Qdd-$Version-setup.exe"', script)
        self.assertIn('"/DOutputBaseFilename=Qdd-$Version-setup"', script)
        self.assertIn(
            'New-Item -ItemType Directory -Path (Join-Path $stagedAppPath "jobs")',
            script,
        )
        self.assertNotIn(
            'Copy-Item -LiteralPath (Join-Path $projectRoot "jobs") -Destination $stagedAppPath',
            script,
        )

    def test_windows_inno_installer_contract(self):
        legacy_name = "QQ" + "JobEditor"
        script = (PROJECT_DIR / "tools" / "build_release.ps1").read_text(
            encoding="utf-8"
        )
        installer = (PROJECT_DIR / "installer" / "Qdd.iss").read_text(
            encoding="utf-8"
        )
        workflow = (
            PROJECT_DIR / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(installer.count("AppId="), 1)
        self.assertIn(
            "AppId={{D2B72385-6B43-4F52-A908-8E381C39141F}",
            installer,
        )
        self.assertIn(r"DefaultDirName={autopf}\Qdd", installer)
        self.assertIn("AppVersion={#AppVersion}", installer)
        self.assertIn("VersionInfoVersion={#AppVersion}.0", installer)
        self.assertIn("SetupIconFile={#IconPath}", installer)
        self.assertIn(r"UninstallDisplayIcon={app}\Qdd.exe", installer)
        self.assertIn(r'Name: "{group}\Qdd"', installer)
        self.assertIn(r'Name: "{autodesktop}\Qdd"', installer)
        self.assertIn('Name: "desktopicon"', installer)
        self.assertIn("Flags: unchecked", installer)
        self.assertIn("PrivilegesRequiredOverridesAllowed=dialog commandline", installer)
        self.assertIn('Excludes: "portable.flag"', installer)
        self.assertIn("[InstallDelete]", installer)
        self.assertIn('Type: files; Name: "{app}\\portable.flag"', installer)
        self.assertNotIn("[UninstallRun]", installer)
        self.assertIn("function PrepareToInstall", installer)
        self.assertIn("procedure CurUninstallStepChanged", installer)
        self.assertIn("StopBundledAdbProcess();", installer)
        self.assertIn(r"{sys}\WindowsPowerShell\v1.0\powershell.exe", installer)
        self.assertIn("StringChangeEx(AdbPath", installer)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", installer)
        self.assertIn("Invoke-CimMethod -InputObject $_ -MethodName Terminate", installer)
        self.assertNotIn('Filename: "{app}\\platform-tools\\adb.exe"', installer)
        self.assertNotIn("Exec(AdbPath", installer)
        self.assertIn("[UninstallDelete]", installer)
        self.assertIn(
            'Type: dirifempty; Name: "{app}\\platform-tools"', installer
        )
        self.assertIn('Type: dirifempty; Name: "{app}"', installer)
        self.assertNotIn("filesandordirs", installer.lower())
        self.assertIn('MessagesFile: "ChineseSimplified.isl"', installer)
        self.assertIn(
            'Source: "ChineseSimplified.LICENSE"; DestDir: "{app}\\licenses"',
            installer,
        )
        self.assertTrue(
            (PROJECT_DIR / "installer" / "ChineseSimplified.isl").is_file()
        )
        translation_license = (
            PROJECT_DIR / "installer" / "ChineseSimplified.LICENSE"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("MIT License", translation_license)
        self.assertNotIn("{localappdata}", installer.lower())
        self.assertNotIn("Copy-RuntimeData", installer)

        self.assertIn("[string]$IsccPath", script)
        self.assertIn("function Resolve-IsccPath", script)
        self.assertIn("[switch]$SkipChecks", script)
        self.assertIn("if (-not $SkipChecks)", script)
        self.assertIn('Get-Command -Name "ISCC.exe"', script)
        self.assertIn(r'Inno Setup 6\ISCC.exe', script)
        self.assertIn("Install Inno Setup 6 or pass -IsccPath", script)
        self.assertIn('"/DSourceDir=$stagedAppPath"', script)
        self.assertIn('"/DIconPath=', script)
        self.assertIn('Write-Output "Installer: $setupPath"', script)

        self.assertIn("choco install innosetup", workflow)
        self.assertIn("Validate schemas", workflow)
        self.assertIn("Run unit tests", workflow)
        self.assertIn("Locate Inno Setup", workflow)
        self.assertIn("steps.inno.outputs.path", workflow)
        self.assertIn("-SkipChecks", workflow)
        self.assertIn("Upload Windows diagnostics", workflow)
        self.assertIn("Windows package build failed", workflow)
        self.assertNotIn("continue-on-error", workflow)
        self.assertIn("release/*.zip", workflow)
        self.assertIn("release/Qdd-*-setup.exe", workflow)

        for label, contents in (
            ("Windows builder", script),
            ("Inno Setup", installer),
            ("release workflow", workflow),
        ):
            with self.subTest(label=label):
                self.assertNotIn(legacy_name, contents)

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
            PROJECT_DIR / ".github" / "workflows" / "release.yml",
            PROJECT_DIR / "installer" / "Qdd.iss",
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

    def test_login_pipeline_targets_nikki_package(self):
        pipeline = (PROJECT_DIR / "assets" / "resource" / "pipeline" / "login.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"package": "com.papegames.nn4"', pipeline)
        self.assertNotIn('"package": "com.tencent.mobileqq"', pipeline)

if __name__ == "__main__":
    unittest.main()
