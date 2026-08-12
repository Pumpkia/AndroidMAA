import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("app_paths.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "app_paths_under_test",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Cannot load {MODULE_PATH}")
app_paths = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = app_paths
MODULE_SPEC.loader.exec_module(app_paths)


def write_file(path: Path, content: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class PathResolutionTests(unittest.TestCase):
    def test_source_mode_keeps_project_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "project"
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=False,
                os_name="nt",
                environ={},
            )

            self.assertTrue(paths.portable)
            self.assertEqual(paths.app_dir, app_dir.resolve())
            self.assertEqual(paths.assets_dir, paths.app_dir / "assets")
            self.assertEqual(paths.data_dir, paths.app_dir)
            self.assertEqual(paths.jobs_dir, paths.app_dir / "jobs")
            self.assertEqual(
                paths.template_dir,
                paths.app_dir / "assets" / "resource" / "image" / "jobs",
            )
            self.assertEqual(paths.logs_dir, paths.app_dir / "logs")
            self.assertEqual(paths.exports_dir, paths.app_dir / "exports")

    def test_windows_frozen_portable_flag_keeps_app_data_and_uses_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "Qdd"
            write_file(app_dir / "portable.flag", "")
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=True,
                os_name="nt",
                environ={"LOCALAPPDATA": str(root / "local")},
            )

            self.assertTrue(paths.portable)
            self.assertEqual(paths.data_dir, app_dir.resolve())
            self.assertEqual(paths.jobs_dir, app_dir.resolve() / "jobs")
            self.assertEqual(
                paths.template_dir,
                app_dir.resolve() / "assets" / "resource" / "image" / "jobs",
            )
            self.assertEqual(paths.exports_dir, app_dir.resolve() / "exports")

    def test_windows_frozen_install_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            local = root / "local"
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=True,
                os_name="nt",
                environ={"LOCALAPPDATA": str(local)},
            )

            data_dir = local.resolve() / "Qdd"
            self.assertFalse(paths.portable)
            self.assertEqual(paths.assets_dir, app_dir.resolve() / "assets")
            self.assertEqual(paths.data_dir, data_dir)
            self.assertEqual(paths.jobs_dir, data_dir / "jobs")
            self.assertEqual(paths.user_resource_dir, data_dir / "resource")
            self.assertEqual(
                paths.template_dir,
                data_dir / "resource" / "image" / "jobs",
            )
            self.assertEqual(paths.logs_dir, data_dir / "logs")
            self.assertEqual(paths.exports_dir, data_dir / "exports")

    def test_missing_local_app_data_falls_back_to_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            paths = app_paths.resolve_app_paths(
                app_dir=root / "app",
                frozen=True,
                os_name="nt",
                environ={},
                home_dir=home,
            )

            self.assertEqual(
                paths.data_dir,
                home.resolve() / "AppData" / "Local" / "Qdd",
            )

    def test_data_dir_override_has_priority_and_uses_installed_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            override = root / "custom-data"
            write_file(app_dir / "portable.flag", "")
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=True,
                os_name="nt",
                environ={
                    "QDD_DATA_DIR": str(override),
                    "LOCALAPPDATA": str(root / "local"),
                },
            )

            self.assertFalse(paths.portable)
            self.assertEqual(paths.data_dir, override.resolve())
            self.assertEqual(
                paths.template_dir,
                override.resolve() / "resource" / "image" / "jobs",
            )
            self.assertEqual(paths.exports_dir, override.resolve() / "exports")

    def test_other_frozen_platform_keeps_existing_app_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "Qdd.app" / "Contents" / "Resources" / "Qdd"
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=True,
                os_name="posix",
                environ={},
            )

            self.assertTrue(paths.portable)
            self.assertEqual(paths.data_dir, app_dir.resolve())
            self.assertEqual(
                paths.exports_dir,
                app_dir.resolve() / "assets" / "resource" / "pipeline",
            )


class LayoutInitializationTests(unittest.TestCase):
    def installed_paths(self, root: Path):
        return app_paths.resolve_app_paths(
            app_dir=root / "app",
            frozen=True,
            os_name="nt",
            environ={"LOCALAPPDATA": str(root / "local")},
        )

    def test_migrates_semantic_map_categories_and_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            write_file(paths.app_dir / "jobs" / "semantic_map.json", '{"regions": []}')
            write_file(
                paths.app_dir / "jobs" / "分类" / "登录.maa_job.json",
                '{"name": "登录", "steps": []}',
            )
            write_file(
                paths.app_dir
                / "assets"
                / "resource"
                / "image"
                / "jobs"
                / "登录"
                / "按钮.png",
                "png",
            )

            result = app_paths.initialize_data_layout(paths)

            self.assertTrue(result.marker_written)
            self.assertFalse(result.already_initialized)
            self.assertEqual(len(result.migrated_files), 3)
            self.assertEqual(
                (paths.jobs_dir / "semantic_map.json").read_text(encoding="utf-8"),
                '{"regions": []}',
            )
            self.assertTrue((paths.jobs_dir / "分类" / "登录.maa_job.json").is_file())
            self.assertTrue((paths.template_dir / "登录" / "按钮.png").is_file())
            marker = json.loads(result.marker_path.read_text(encoding="utf-8"))
            self.assertEqual(marker["version"], 1)
            self.assertEqual(len(marker["migrated_files"]), 3)

    def test_existing_files_are_not_overwritten_and_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            source = paths.app_dir / "jobs" / "默认" / "case.maa_job.json"
            destination = paths.jobs_dir / "默认" / "case.maa_job.json"
            write_file(source, "source")
            write_file(destination, "destination")

            first = app_paths.initialize_data_layout(paths)
            write_file(paths.app_dir / "jobs" / "late.maa_job.json", "late")
            second = app_paths.initialize_data_layout(paths)

            self.assertEqual(destination.read_text(encoding="utf-8"), "destination")
            self.assertIn(destination, first.skipped_files)
            self.assertTrue(first.marker_written)
            self.assertTrue(second.already_initialized)
            self.assertFalse(second.marker_written)
            self.assertEqual(second.migrated_files, ())
            self.assertFalse((paths.jobs_dir / "late.maa_job.json").exists())

    def test_invalid_marker_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            marker = paths.data_dir / app_paths.LAYOUT_MARKER_NAME
            write_file(marker, "not-json")
            write_file(paths.app_dir / "jobs" / "case.maa_job.json", "{}")

            result = app_paths.initialize_data_layout(paths)

            self.assertTrue(result.marker_written)
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8"))["version"],
                1,
            )
            self.assertTrue((paths.jobs_dir / "case.maa_job.json").is_file())

    def test_symbolic_link_entries_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            linked_file = paths.app_dir / "jobs" / "linked.maa_job.json"
            linked_directory = paths.app_dir / "jobs" / "linked-category"
            write_file(linked_file, "{}")
            write_file(linked_directory / "case.maa_job.json", "{}")
            real_is_symlink = Path.is_symlink

            def simulated_symlink(path):
                if path in {linked_file, linked_directory}:
                    return True
                return real_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", simulated_symlink):
                result = app_paths.initialize_data_layout(paths)

            self.assertIn(linked_file, result.skipped_files)
            self.assertIn(linked_directory, result.skipped_files)
            self.assertFalse((paths.jobs_dir / linked_file.name).exists())
            self.assertFalse((paths.jobs_dir / linked_directory.name).exists())

    def test_copy_failure_does_not_write_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            write_file(paths.app_dir / "jobs" / "case.maa_job.json", "{}")

            with mock.patch.object(
                app_paths.shutil,
                "copy2",
                side_effect=OSError("simulated copy failure"),
            ):
                with self.assertRaises(OSError):
                    app_paths.initialize_data_layout(paths)

            marker = paths.data_dir / app_paths.LAYOUT_MARKER_NAME
            self.assertFalse(marker.exists())
            self.assertEqual(list(paths.jobs_dir.glob(".*.tmp")), [])

    def test_marker_failure_leaves_copied_data_but_no_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            write_file(paths.app_dir / "jobs" / "case.maa_job.json", "{}")
            real_replace = app_paths.os.replace

            def fail_marker_replace(source, destination):
                if Path(destination).name == app_paths.LAYOUT_MARKER_NAME:
                    raise OSError("simulated marker failure")
                return real_replace(source, destination)

            with mock.patch.object(
                app_paths.os,
                "replace",
                side_effect=fail_marker_replace,
            ):
                with self.assertRaises(OSError):
                    app_paths.initialize_data_layout(paths)

            marker = paths.data_dir / app_paths.LAYOUT_MARKER_NAME
            self.assertFalse(marker.exists())
            self.assertTrue((paths.jobs_dir / "case.maa_job.json").is_file())
            self.assertEqual(list(paths.data_dir.glob(".*.tmp")), [])

    def test_data_root_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            paths.data_dir.mkdir(parents=True)
            real_check = app_paths._is_link_or_junction

            def simulated_link(path):
                if path == paths.data_dir:
                    return True
                return real_check(path)

            with mock.patch.object(
                app_paths,
                "_is_link_or_junction",
                side_effect=simulated_link,
            ):
                with self.assertRaisesRegex(RuntimeError, "link or junction"):
                    app_paths.initialize_data_layout(paths)

            self.assertFalse(
                (paths.data_dir / app_paths.LAYOUT_MARKER_NAME).exists()
            )

    def test_target_intermediate_junction_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            paths.user_resource_dir.mkdir(parents=True)
            real_check = app_paths._is_link_or_junction

            def simulated_junction(path):
                if path == paths.user_resource_dir:
                    return True
                return real_check(path)

            with mock.patch.object(
                app_paths,
                "_is_link_or_junction",
                side_effect=simulated_junction,
            ):
                with self.assertRaisesRegex(RuntimeError, "link or junction"):
                    app_paths.initialize_data_layout(paths)

            self.assertFalse(
                (paths.data_dir / app_paths.LAYOUT_MARKER_NAME).exists()
            )

    def test_junction_outside_data_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            external_parent = paths.data_dir.parent
            external_parent.mkdir(parents=True)
            real_check = app_paths._is_link_or_junction

            def simulated_junction(path):
                if path == external_parent:
                    return True
                return real_check(path)

            with mock.patch.object(
                app_paths,
                "_is_link_or_junction",
                side_effect=simulated_junction,
            ):
                result = app_paths.initialize_data_layout(paths)

            self.assertTrue(result.marker_written)
            self.assertTrue(paths.jobs_dir.is_dir())

    def test_source_junction_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            source_junction = paths.app_dir / "jobs" / "junction-category"
            write_file(source_junction / "case.maa_job.json", "{}")
            existing_os_check = getattr(app_paths.os.path, "isjunction", None)

            def simulated_junction(path):
                if Path(path) == source_junction:
                    return True
                if callable(existing_os_check):
                    return bool(existing_os_check(path))
                return False

            with mock.patch.object(
                app_paths.os.path,
                "isjunction",
                create=True,
                side_effect=simulated_junction,
            ):
                result = app_paths.initialize_data_layout(paths)

            self.assertIn(source_junction, result.skipped_files)
            self.assertFalse((paths.jobs_dir / source_junction.name).exists())

    def test_concurrent_destination_creation_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.installed_paths(root)
            source = paths.app_dir / "jobs" / "case.maa_job.json"
            destination = paths.jobs_dir / source.name
            write_file(source, "legacy")
            real_link = app_paths.os.link

            def publish_concurrent_file(source_temp, target, *args, **kwargs):
                if Path(target) == destination and not destination.exists():
                    write_file(destination, "concurrent")
                return real_link(source_temp, target, *args, **kwargs)

            with mock.patch.object(
                app_paths.os,
                "link",
                side_effect=publish_concurrent_file,
            ):
                result = app_paths.initialize_data_layout(paths)

            self.assertEqual(destination.read_text(encoding="utf-8"), "concurrent")
            self.assertIn(destination, result.skipped_files)
            self.assertTrue(result.marker_written)
            self.assertEqual(
                list(destination.parent.glob(f".{destination.name}.migrate-*.tmp")),
                [],
            )


    def test_portable_layout_creates_directories_without_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "project"
            paths = app_paths.resolve_app_paths(
                app_dir=app_dir,
                frozen=False,
                os_name="nt",
                environ={},
            )

            result = app_paths.initialize_data_layout(paths)

            self.assertFalse(result.marker_written)
            self.assertFalse(result.marker_path.exists())
            self.assertTrue(paths.jobs_dir.is_dir())
            self.assertTrue(paths.template_dir.is_dir())
            self.assertTrue(paths.logs_dir.is_dir())
            self.assertTrue(paths.exports_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
