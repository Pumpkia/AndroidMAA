from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qt_workbench import AdbClient, run_job_with_retry, write_png


class FakeRunner:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def run(self, _document, _serial, _emit):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class RetryPolicyTests(unittest.TestCase):
    def test_success_does_not_retry(self):
        runner = FakeRunner([True])
        messages = []

        succeeded = run_job_with_retry(runner, object(), "device", messages.append, True)

        self.assertTrue(succeeded)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(messages, [])

    def test_failure_retries_once(self):
        runner = FakeRunner([False, True])
        messages = []

        succeeded = run_job_with_retry(runner, object(), "device", messages.append, True)

        self.assertTrue(succeeded)
        self.assertEqual(runner.calls, 2)
        self.assertEqual(messages, ["首次执行失败，正在重试一次"])

    def test_stop_request_prevents_retry(self):
        runner = FakeRunner([False, True])
        messages = []

        succeeded = run_job_with_retry(
            runner,
            object(),
            "device",
            messages.append,
            True,
            lambda: True,
        )

        self.assertFalse(succeeded)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(messages, [])

    def test_exception_is_reported_as_failure(self):
        runner = FakeRunner([RuntimeError("连接断开")])
        messages = []

        succeeded = run_job_with_retry(runner, object(), "device", messages.append, False)

        self.assertFalse(succeeded)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(messages, ["用例异常：连接断开"])


class ImageWriteTests(unittest.TestCase):
    def test_write_png_supports_unicode_path(self):
        image = np.full((12, 18, 3), 127, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "失败截图.png"

            self.assertTrue(write_png(output, image))
            loaded = cv2.imdecode(np.fromfile(output, dtype=np.uint8), cv2.IMREAD_COLOR)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.shape, image.shape)


class AdbClientTests(unittest.TestCase):
    def test_shell_returns_command_stdout(self):
        client = AdbClient()
        client.run = lambda _args: SimpleNamespace(
            returncode=0, stdout=b"result", stderr=b""
        )

        self.assertEqual(client.shell(["echo", "value"]), b"result")


if __name__ == "__main__":
    unittest.main()