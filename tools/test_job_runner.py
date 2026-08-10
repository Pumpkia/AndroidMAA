from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_runner import MAA_COORDINATE_SHORT_SIDE, controller_runtime_device_size


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


if __name__ == "__main__":
    unittest.main()
