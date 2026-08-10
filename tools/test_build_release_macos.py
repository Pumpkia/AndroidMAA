import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("build_release_macos.py")
MODULE_SPEC = importlib.util.spec_from_file_location("build_release_macos_under_test", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Cannot load {MODULE_PATH}")
release = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(release)


def write_file(path: Path, content: str | bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def make_launcher(bundle_path: Path) -> Path:
    launcher = bundle_path / "Contents" / "MacOS" / release.APP_NAME
    write_file(launcher, b"launcher")
    return launcher


class MacOSReleaseTests(unittest.TestCase):
    def test_qdd_brand_icon_and_plist(self):
        self.assertEqual(release.APP_NAME, "Qdd")
        self.assertEqual(release.MACOS_SPEC_NAME, "Qdd.macos.spec")
        self.assertEqual(release.BUNDLE_IDENTIFIER, "com.pumpkia.androidmaa.qdd")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            packaged_dir = root / "packaged"
            write_file(packaged_dir / release.APP_NAME, b"executable")
            icon_path = root / "qdd.icns"
            icon_payload = b"icns" + (12).to_bytes(4, "big") + b"icon"
            write_file(icon_path, icon_payload)
            bundle_path = root / "Qdd.app"

            release.write_app_bundle(
                bundle_path,
                packaged_dir,
                "v2.1.0",
                icon_path=icon_path,
            )

            with (bundle_path / "Contents" / "Info.plist").open("rb") as file:
                info = plistlib.load(file)
            self.assertEqual(info["CFBundleDisplayName"], "Qdd")
            self.assertEqual(info["CFBundleExecutable"], "Qdd")
            self.assertEqual(info["CFBundleIdentifier"], release.BUNDLE_IDENTIFIER)
            self.assertEqual(info["CFBundleIconFile"], "qdd.icns")
            self.assertEqual(
                (bundle_path / "Contents" / "Resources" / "qdd.icns").read_bytes(),
                icon_payload,
            )
            self.assertTrue((release.bundle_runtime_dir(bundle_path) / "Qdd").is_file())

    def test_clean_stage_excludes_jobs_recordings_and_debug_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            packaged_dir = root / "packaged"
            platform_tools = root / "darwin-platform-tools"

            write_file(project_root / "assets" / "config" / "app.json", "{}")
            write_file(
                project_root / "assets" / "resource" / "image" / "jobs" / "private.png"
            )
            write_file(project_root / "assets" / "debug" / "private.log")
            write_file(project_root / "jobs" / "private.maa_job.json", "{}")
            write_file(project_root / "README.md", "# Qdd\n")
            write_file(platform_tools / "adb", b"adb")
            write_file(
                packaged_dir
                / "_internal"
                / "MaaAgentBinary"
                / "maatouch"
                / "universal"
                / "maatouch",
                b"maatouch",
            )

            release.stage_clean_runtime_data(
                packaged_dir,
                platform_tools,
                project_root=project_root,
            )

            self.assertEqual(list((packaged_dir / "jobs").iterdir()), [])
            self.assertFalse(
                (packaged_dir / "assets" / "resource" / "image" / "jobs").exists()
            )
            self.assertFalse((packaged_dir / "assets" / "debug").exists())
            self.assertTrue((packaged_dir / "assets" / "config" / "app.json").is_file())
            self.assertTrue((packaged_dir / "platform-tools" / "adb").is_file())
            self.assertTrue((project_root / "jobs" / "private.maa_job.json").is_file())

    def test_template_path_validation_rejects_traversal_and_absolute_paths(self):
        self.assertEqual(
            release.safe_template_relative_path(r"jobs\demo\button.png").parts,
            ("jobs", "demo", "button.png"),
        )
        invalid = (
            "../secret.png",
            "jobs/../../secret.png",
            "/tmp/secret.png",
            r"C:\secret.png",
            r"C:secret.png",
            r"\\server\share\secret.png",
            "",
            None,
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(release.safe_template_relative_path(value))

    def test_preserve_local_data_keeps_jobs_and_only_safe_referenced_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_bundle = root / "old" / "Qdd.app"
            new_bundle = root / "new" / "Qdd.app"
            old_runtime = release.bundle_runtime_dir(old_bundle)
            new_runtime = release.bundle_runtime_dir(new_bundle)
            old_jobs = old_runtime / "jobs"
            old_images = old_runtime / "assets" / "resource" / "image"
            new_images = new_runtime / "assets" / "resource" / "image"
            (new_runtime / "jobs").mkdir(parents=True)
            new_images.mkdir(parents=True)

            absolute_template = root / "absolute-private.png"
            write_file(absolute_template)
            job = {
                "steps": [
                    {"template": "jobs/demo/good.png"},
                    {"template": "../escape.png"},
                    {"template": str(absolute_template)},
                    {"template": r"C:\private.png"},
                    {"template": "jobs/demo/missing.png"},
                ]
            }
            write_file(
                old_jobs / "demo.maa_job.json",
                json.dumps(job, ensure_ascii=False),
            )
            write_file(old_jobs / "broken.maa_job.json", "{broken")
            write_file(old_jobs / "semantic_map.json", '{"regions": []}')
            write_file(old_images / "jobs" / "demo" / "good.png", b"good")
            write_file(old_images / "jobs" / "demo" / "unused.png", b"unused")
            write_file(old_images.parent / "escape.png", b"escape")

            copied = release.preserve_local_data(old_bundle, new_bundle)

            self.assertEqual(copied, [Path("jobs") / "demo" / "good.png"])
            self.assertTrue((new_runtime / "jobs" / "demo.maa_job.json").is_file())
            self.assertTrue((new_runtime / "jobs" / "broken.maa_job.json").is_file())
            self.assertTrue((new_runtime / "jobs" / "semantic_map.json").is_file())
            self.assertEqual(
                (new_images / "jobs" / "demo" / "good.png").read_bytes(),
                b"good",
            )
            self.assertFalse((new_images / "jobs" / "demo" / "unused.png").exists())
            self.assertFalse((new_images.parent / "escape.png").exists())

    def test_blank_runtime_guard_rejects_jobs_and_recorded_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "Qdd.app"
            runtime = release.bundle_runtime_dir(bundle)
            (runtime / "jobs").mkdir(parents=True)
            release.verify_blank_runtime_data(bundle)

            write_file(runtime / "jobs" / "private.json", "{}")
            with self.assertRaises(RuntimeError):
                release.verify_blank_runtime_data(bundle)
            shutil.rmtree(runtime / "jobs")
            (runtime / "jobs").mkdir()
            (runtime / "assets" / "resource" / "image" / "jobs").mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                release.verify_blank_runtime_data(bundle)

    def test_artifact_names_and_darwin_adb_are_host_independent(self):
        archive, dmg = release.artifact_paths(Path("release"), "v2.1.0", "macos-arm64")
        self.assertEqual(archive.name, "Qdd-v2.1.0-macos-arm64.zip")
        self.assertEqual(dmg.name, "Qdd-v2.1.0-macos-arm64.dmg")
        self.assertEqual(release.platform_tag("AMD64"), "macos-x86_64")
        self.assertEqual(release.platform_tag("aarch64"), "macos-arm64")

        with tempfile.TemporaryDirectory() as temp_dir:
            platform_tools = Path(temp_dir)
            write_file(platform_tools / "adb", b"darwin-adb")
            self.assertEqual(release.selected_platform_tools(platform_tools), platform_tools)

    def test_release_artifacts_precede_restore_resign_and_promotion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "stage" / "Qdd.app"
            runtime = release.bundle_runtime_dir(bundle)
            (runtime / "jobs").mkdir(parents=True)
            canonical = root / "dist" / "Qdd.app"
            canonical.mkdir(parents=True)
            backup = root / "stage" / "previous-app"
            calls: list[str] = []

            with (
                mock.patch.object(
                    release, "sign_app_bundle", side_effect=lambda _path: calls.append("sign")
                ),
                mock.patch.object(
                    release,
                    "create_release_artifacts",
                    side_effect=lambda *args, **kwargs: (
                        calls.append("artifacts")
                        or (root / "release.zip", root / "release.dmg")
                    ),
                ),
                mock.patch.object(
                    release,
                    "preserve_local_data",
                    side_effect=lambda *args: calls.append("restore") or [],
                ),
                mock.patch.object(
                    release,
                    "promote_app_bundle",
                    side_effect=lambda *args: calls.append("promote"),
                ),
            ):
                release.finalize_release(
                    bundle,
                    canonical,
                    backup,
                    root / "release",
                    "v2.1.0",
                    "macos-arm64",
                    skip_dmg=False,
                )

            self.assertEqual(
                calls,
                ["sign", "artifacts", "restore", "sign", "promote"],
            )

    def test_failed_promotion_rolls_back_previous_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "stage" / "Qdd.app"
            canonical = root / "dist" / "Qdd.app"
            backup = root / "stage" / "previous-app"
            make_launcher(candidate)
            write_file(canonical / "old-data.txt", b"old")
            real_move = shutil.move

            def fail_candidate_move(source, destination):
                if Path(source) == candidate:
                    raise OSError("simulated promotion failure")
                return real_move(source, destination)

            with mock.patch.object(release.shutil, "move", side_effect=fail_candidate_move):
                with self.assertRaises(OSError):
                    release.promote_app_bundle(candidate, canonical, backup)

            self.assertEqual((canonical / "old-data.txt").read_bytes(), b"old")
            self.assertFalse(backup.exists())
            self.assertTrue(candidate.exists())


if __name__ == "__main__":
    unittest.main()
