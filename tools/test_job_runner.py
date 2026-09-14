import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_runner import (
    MAA_COORDINATE_SHORT_SIDE,
    MaaJobRunner,
    controller_runtime_device_size,
)


class FakeScreenshotJob:
    def __init__(self, shape=(1280, 720, 3), succeeded=True):
        self.image = SimpleNamespace(shape=shape)
        self.succeeded = succeeded
        self.waited = False

    def wait(self):
        self.waited = True
        return self

    def get(self):
        return self.image


class FakeController:
    def __init__(self, job):
        self.job = job
        self.short_side = None

    def set_screenshot_target_short_side(self, value):
        self.short_side = value
        return True

    def post_screencap(self):
        return self.job


class RuntimeDeviceSizeTests(unittest.TestCase):
    def test_uses_maa_short_side_screenshot_dimensions(self):
        job = FakeScreenshotJob(shape=(1280, 720, 3))
        controller = FakeController(job)

        size = controller_runtime_device_size(controller)

        self.assertEqual(controller.short_side, MAA_COORDINATE_SHORT_SIDE)
        self.assertEqual(MAA_COORDINATE_SHORT_SIDE, 720)
        self.assertTrue(job.waited)
        self.assertEqual(size, [720, 1280])

    def test_rejects_failed_screenshot(self):
        with self.assertRaisesRegex(RuntimeError, "capture"):
            controller_runtime_device_size(
                FakeController(FakeScreenshotJob(succeeded=False))
            )


class FakeBundleJob:
    def __init__(self, succeeded=True):
        self.succeeded = succeeded
        self.waited = False

    def wait(self):
        self.waited = True
        return self


class FakeResource:
    def __init__(self, results=None):
        self.results = iter(results or [True, True])
        self.directories = []
        self.jobs = []

    def post_bundle(self, directory):
        self.directories.append(Path(directory))
        job = FakeBundleJob(next(self.results))
        self.jobs.append(job)
        return job


class ResourceBundleTests(unittest.TestCase):
    def test_loads_builtin_resource_then_user_overlay(self):
        runner = MaaJobRunner(
            Path("app"),
            Path("install/assets"),
            Path("jobs"),
            user_resource_dir=Path("user/resource"),
        )
        resource = FakeResource()

        result = runner._post_resource_bundles(resource)

        self.assertTrue(result.succeeded)
        self.assertEqual(
            resource.directories,
            [Path("install/assets/resource"), Path("user/resource")],
        )
        self.assertTrue(all(job.waited for job in resource.jobs))

    def test_legacy_constructor_loads_once_and_duplicate_overlay_is_removed(self):
        legacy = MaaJobRunner(Path("app"), Path("assets"), Path("jobs"))
        resource = FakeResource([True])

        legacy._post_resource_bundles(resource)

        self.assertIsNone(legacy.user_resource_dir)
        self.assertEqual(legacy.user_data_dir, Path("jobs").parent)
        self.assertEqual(resource.directories, [Path("assets/resource")])

        duplicate = Path("assets/resource/../resource")
        runner = MaaJobRunner(
            Path("app"), Path("assets"), Path("jobs"),
            user_resource_dir=duplicate,
        )
        resource = FakeResource([True])

        runner._post_resource_bundles(resource)

        self.assertEqual(resource.directories, [Path("assets/resource")])

    def test_toolkit_uses_user_data_directory_not_installed_assets(self):
        assets_dir = Path("Program Files/NnMaa/assets")
        data_dir = Path("LocalAppData/NnMaa")
        runner = MaaJobRunner(
            Path("Program Files/NnMaa"),
            assets_dir,
            data_dir / "jobs",
            user_resource_dir=data_dir / "resource",
            user_data_dir=data_dir,
        )
        default_config = {"logging": True}

        with (
            patch.object(runner, "_load_default_config", return_value=default_config),
            patch("job_runner.Toolkit.init_option") as init_option,
            patch("job_runner.Toolkit.find_adb_devices", return_value=[]),
        ):
            with self.assertRaises(RuntimeError):
                runner.run(object(), "missing", lambda _message: None)

        init_option.assert_called_once_with(data_dir, default_config)
        self.assertNotEqual(init_option.call_args.args[0], assets_dir)

    def test_loads_default_config_from_builtin_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            config_path = assets_dir / "config" / "maa_option.json"
            config_path.parent.mkdir(parents=True)
            expected = {"draw_quality": 85, "logging": True}
            config_path.write_text(json.dumps(expected), encoding="utf-8")
            runner = MaaJobRunner(Path(temp_dir), assets_dir, Path(temp_dir) / "jobs")

            self.assertEqual(runner._load_default_config(), expected)

    def test_missing_default_config_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            runner = MaaJobRunner(Path(temp_dir), assets_dir, Path(temp_dir) / "jobs")

            with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                runner._load_default_config()

    def test_invalid_default_config_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            config_path = assets_dir / "config" / "maa_option.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{not-json", encoding="utf-8")
            runner = MaaJobRunner(Path(temp_dir), assets_dir, Path(temp_dir) / "jobs")

            with self.assertRaisesRegex(RuntimeError, "configuration is invalid"):
                runner._load_default_config()

    def test_default_config_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            config_path = assets_dir / "config" / "maa_option.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("[]", encoding="utf-8")
            runner = MaaJobRunner(Path(temp_dir), assets_dir, Path(temp_dir) / "jobs")

            with self.assertRaisesRegex(RuntimeError, "must be a JSON object"):
                runner._load_default_config()

if __name__ == "__main__":
    unittest.main()
