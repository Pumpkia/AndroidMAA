from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication, QFrame, QTableWidget

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qt_workbench import (
    AdbClient,
    PlaybackPage,
    PlaybackResult,
    RecordingGeometry,
    Workbench,
    click_target_point,
    normalize_recording_image,
    run_job_with_retry,
    run_playback_queue,
    write_png,
)
from job_model import JobDocument, JobStep


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


class PlaybackQueueTests(unittest.TestCase):
    def test_failure_stops_queue_and_marks_remaining_as_skipped(self):
        runner = FakeRunner([False, True])
        statuses = []
        progress = []

        result = run_playback_queue(
            [Path("first.maa_job.json"), Path("second.maa_job.json")],
            "device",
            runner,
            lambda _message: None,
            False,
            lambda: False,
            lambda row, status: statuses.append((row, status)),
            progress.append,
            load_document=lambda path: path,
        )

        self.assertEqual(runner.calls, 1)
        self.assertEqual(result.succeeded, 0)
        self.assertEqual(result.failed_index, 0)
        self.assertFalse(result.stopped)
        self.assertEqual(
            statuses,
            [(0, "执行中"), (0, "失败"), (1, "已跳过")],
        )
        self.assertEqual(progress, [50])

    def test_success_continues_to_next_job(self):
        runner = FakeRunner([True, True])
        statuses = []

        result = run_playback_queue(
            [Path("first.maa_job.json"), Path("second.maa_job.json")],
            "device",
            runner,
            lambda _message: None,
            False,
            lambda: False,
            lambda row, status: statuses.append((row, status)),
            lambda _value: None,
            load_document=lambda path: path,
        )

        self.assertEqual(runner.calls, 2)
        self.assertEqual(result.succeeded, 2)
        self.assertIsNone(result.failed_index)
        self.assertEqual(statuses[-1], (1, "已完成"))

    def test_failed_result_sets_overall_failed_state(self):
        active_states = []
        run_states = []
        logs = []
        finished = []
        page = SimpleNamespace(
            set_execution_active=active_states.append,
            set_state=lambda text, state: run_states.append((text, state)),
            append_log=logs.append,
            app=SimpleNamespace(
                finish_close_if_requested=lambda: finished.append(True)
            ),
        )

        PlaybackPage.execution_finished(
            page,
            PlaybackResult(succeeded=0, total=2, failed_index=0),
        )

        self.assertEqual(active_states, [False])
        self.assertEqual(run_states, [("失败", "failed")])
        self.assertEqual(logs, ["执行结束：成功 0 / 2"])
        self.assertEqual(finished, [True])


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

    def test_click_target_point_accepts_point_and_region(self):
        self.assertEqual(click_target_point([120, 300]), (120, 300))
        self.assertEqual(click_target_point([100, 200, 80, 40]), (140, 220))

    def test_execute_clicks_center_of_region_target(self):
        client = AdbClient()
        client.serial = "device"
        commands = []
        client.shell = lambda args: commands.append(args)
        step = SimpleNamespace(
            action="Click",
            target=[100, 200, 80, 40],
            pre_delay=0,
            post_delay=0,
        )

        client.execute(step)

        self.assertEqual(commands, [["input", "tap", "140", "220"]])


class VisualSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_apple_style_navigation_and_tables_are_applied(self):
        with patch.object(Workbench, "refresh_devices", lambda _window: None):
            window = Workbench()

        try:
            self.assertIsNotNone(window.findChild(QFrame, "modeSwitcher"))
            self.assertIn("#0066CC", window.styleSheet())
            self.assertIn("#modeSwitcher", window.styleSheet())
            semantic = window.semantic
            self.assertEqual(semantic.scan_table.columnCount(), 5)
            self.assertEqual(
                [semantic.region_type.itemData(index) for index in range(3)],
                ["click", "check", "recognize"],
            )
            semantic.region_type.setCurrentIndex(1)
            self.assertFalse(semantic.destination.isEnabled())
            semantic.set_busy(True)
            semantic.set_busy(False)
            self.assertFalse(semantic.destination.isEnabled())
            semantic.region_type.setCurrentIndex(0)
            self.assertTrue(semantic.destination.isEnabled())
            self.assertFalse(semantic.test_tap_button.isEnabled())
            self.assertTrue(
                all(table.alternatingRowColors() for table in window.findChildren(QTableWidget))
            )
            for index, expected in enumerate(
                ((True, False, False), (False, True, False), (False, False, True))
            ):
                window.switch_page(index)
                self.assertEqual(
                    (
                        window.record_button.isChecked(),
                        window.play_button.isChecked(),
                        window.semantic_button.isChecked(),
                    ),
                    expected,
                )
        finally:
            window.close()



class SemanticStepEditorRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def make_window(self, steps):
        with patch.object(Workbench, "refresh_devices", lambda _window: None):
            window = Workbench()
        window.document = JobDocument(name="\u8bed\u4e49\u7528\u4f8b", category="\u9ed8\u8ba4", steps=steps)
        window.record.refresh_steps(0)
        return window

    @staticmethod
    def semantic_step(purpose):
        return JobStep(
            name={"click": "\u6253\u5f00\u8bbe\u7f6e", "check": "\u68c0\u67e5\u6807\u9898", "recognize": "\u8bc6\u522b\u72b6\u6001"}[purpose],
            recognition="OCR",
            action="Click" if purpose == "click" else "DoNothing",
            roi=[10, 20, 120, 40],
            expected="\u8bbe\u7f6e",
            target=[8, 16, 160, 56] if purpose == "click" else None,
            semantic_purpose=purpose,
        )

    def test_semantic_purpose_survives_record_page_edit_round_trip(self):
        steps = [self.semantic_step(purpose) for purpose in ("click", "check", "recognize")]
        window = self.make_window(steps)

        try:
            expected_labels = ("\u8bed\u4e49\u70b9\u51fb", "\u8bed\u4e49\u68c0\u67e5", "\u8bed\u4e49\u8bc6\u522b")
            self.assertEqual(
                [window.record.steps.item(row, 2).text() for row in range(3)],
                list(expected_labels),
            )
            for row, (purpose, label) in enumerate(
                zip(("click", "check", "recognize"), expected_labels)
            ):
                window.record.steps.selectRow(row)
                window.record.name.setText(f"{label}-\u5df2\u7f16\u8f91")

                self.assertEqual(window.record.purpose_info.text(), label)
                self.assertFalse(window.record.recognition.isEnabled())
                self.assertFalse(window.record.action.isEnabled())

                with patch("qt_workbench.QMessageBox.warning") as warning:
                    window.record.update_step()
                warning.assert_not_called()

                updated = window.document.steps[row]
                self.assertEqual(updated.semantic_purpose, purpose)
                self.assertEqual(updated.name, f"{label}-\u5df2\u7f16\u8f91")
                self.assertEqual(updated.validate(), [])
        finally:
            window.set_dirty(False)
            window.close()

    def test_semantic_step_cannot_be_changed_to_incompatible_action(self):
        original = self.semantic_step("check")
        window = self.make_window([original])

        try:
            window.record.action.setCurrentIndex(window.record.action.findData("Click"))
            with patch("qt_workbench.QMessageBox.warning") as warning:
                window.record.update_step()

            self.assertEqual(window.document.steps[0], original)
            warning.assert_called_once()
            self.assertIn("DoNothing", warning.call_args.args[2])
        finally:
            window.set_dirty(False)
            window.close()


class RecordingCoordinateTests(unittest.TestCase):
    def test_normalize_1080_by_2400_to_720_by_1600(self):
        raw = np.zeros((2400, 1080, 3), dtype=np.uint8)

        normalized, geometry = normalize_recording_image(raw)

        self.assertEqual(normalized.shape[:2], (1600, 720))
        self.assertEqual(raw.shape[:2], (2400, 1080))
        self.assertEqual(geometry.physical_size, (1080, 2400))
        self.assertEqual(geometry.normalized_size, (720, 1600))
        self.assertEqual(geometry.scale_to_physical, (1.5, 1.5))

    def test_adb_screenshot_keeps_physical_resolution(self):
        raw = np.zeros((2400, 1080, 3), dtype=np.uint8)
        succeeded, encoded = cv2.imencode(".png", raw)
        self.assertTrue(succeeded)
        client = AdbClient()
        client.run = lambda _args: SimpleNamespace(
            returncode=0, stdout=encoded.tobytes(), stderr=b""
        )

        screenshot = client.screenshot()

        self.assertEqual(screenshot.shape[:2], (2400, 1080))

    def test_execute_maps_click_and_swipe_back_to_physical_coordinates(self):
        client = AdbClient()
        client.serial = "device"
        client.recording_geometry = RecordingGeometry((1080, 2400), (720, 1600))
        commands = []
        client.shell = lambda args: commands.append(args)
        click = SimpleNamespace(
            action="Click", target=[100, 200, 80, 40],
            pre_delay=0, post_delay=0,
        )
        swipe = SimpleNamespace(
            action="Swipe", target=[100, 200], swipe_end=[300, 400],
            duration=500, pre_delay=0, post_delay=0,
        )

        client.execute(click)
        client.execute(swipe)

        self.assertEqual(commands[0], ["input", "tap", "210", "330"])
        self.assertEqual(
            commands[1],
            ["input", "swipe", "150", "300", "450", "600", "500"],
        )

    def test_semantic_click_materializes_ratio_on_current_physical_screen(self):
        client = AdbClient()
        client.serial = "device"
        client.recording_geometry = RecordingGeometry((1080, 1920), (720, 1280))
        commands = []
        client.shell = lambda args: commands.append(args)
        step = SimpleNamespace(
            action="Click",
            target=[72, 1280, 360, 160],
            target_ratio=[0.1, 0.8, 0.6, 0.9],
            semantic_purpose="click",
            pre_delay=0,
            post_delay=0,
        )

        client.execute(step)

        self.assertEqual(commands, [["input", "tap", "378", "1632"]])


class WorkbenchCaptureAndRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    @staticmethod
    def make_window():
        with patch.object(Workbench, "refresh_devices", lambda _window: None):
            return Workbench()

    @staticmethod
    def close_window(window):
        window.execution_active = False
        window.set_dirty(False)
        window.close()

    def test_capture_uses_normalized_image_and_document_size(self):
        window = self.make_window()
        raw = np.zeros((2400, 1080, 3), dtype=np.uint8)
        session = SimpleNamespace(screenshot=lambda: raw)
        serials = []
        window.adb.serial = "physical-device"
        window.adb.for_serial = lambda serial: (serials.append(serial) or session)
        window.run_async = lambda operation, done=None, failed=None: done(operation())

        try:
            window.capture_screen()

            self.assertEqual(serials, ["physical-device"])
            self.assertEqual(window.screen_image.shape[:2], (1600, 720))
            self.assertEqual(window.document.device_size, [720, 1600])
            self.assertEqual(window.record.canvas.source_size.width(), 720)
            self.assertEqual(window.record.canvas.source_size.height(), 1600)
            self.assertEqual(
                window.adb.recording_geometry.scale_to_physical,
                (1.5, 1.5),
            )
        finally:
            self.close_window(window)

    def test_capture_discards_result_after_device_switch(self):
        window = self.make_window()
        raw = np.zeros((2400, 1080, 3), dtype=np.uint8)
        callbacks = {}
        window.adb.serial = "first"
        window.adb.for_serial = lambda _serial: SimpleNamespace(screenshot=lambda: raw)
        window.run_async = lambda operation, done=None, failed=None: callbacks.update(
            operation=operation, done=done
        )

        try:
            window.capture_screen()
            window.adb.serial = "second"
            callbacks["done"](raw)

            self.assertIsNone(window.screen_image)
            self.assertIsNone(window.adb.recording_geometry)
            self.assertIn("\u5df2\u4e22\u5f03", window.message_status.text())
        finally:
            self.close_window(window)

    def test_device_change_clears_recording_geometry(self):
        window = self.make_window()
        window.adb.serial = "first"
        window.adb.recording_geometry = RecordingGeometry((1080, 2400), (720, 1600))
        window.screen_image = np.zeros((1600, 720, 3), dtype=np.uint8)

        try:
            window.device_changed("second")

            self.assertIsNone(window.adb.recording_geometry)
            self.assertIsNone(window.screen_image)
            self.assertIsNone(window.record.canvas.pixmap)
        finally:
            self.close_window(window)

    def test_refresh_ignores_stale_generation_and_active_execution(self):
        window = self.make_window()
        callbacks = []
        window.run_async = lambda operation, done=None, failed=None: callbacks.append(done)

        try:
            window.refresh_devices()
            first = callbacks[-1]
            window.refresh_devices()
            second = callbacks[-1]
            first(["stale"])
            self.assertEqual(window.devices.count(), 0)

            second(["fresh"])
            self.assertGreaterEqual(window.devices.findText("fresh"), 0)

            window.refresh_devices()
            active_result = callbacks[-1]
            window.set_execution_active(True, "semantic")
            active_result(["must-not-replace"])
            self.assertEqual(window.devices.findText("must-not-replace"), -1)
        finally:
            self.close_window(window)

    def test_preview_uses_bound_session_and_releases_active_state(self):
        window = self.make_window()
        step = JobStep(
            name="tap", recognition="DirectHit", action="Click",
            target=[10, 20], pre_delay=0, post_delay=0,
        )
        window.document.steps = [step]
        window.record.refresh_steps(0)
        window.adb.serial = "device"
        executed = []
        session = SimpleNamespace(execute=lambda value: executed.append(value))
        window.adb.for_serial = lambda _serial: session
        window.adb.execute = lambda _step: (_ for _ in ()).throw(
            AssertionError("shared adb must not execute preview")
        )
        active = []
        window.set_execution_active = lambda *args: active.append(args)
        finished = []
        window.finish_close_if_requested = lambda: finished.append(True)
        window.run_async = lambda operation, done=None, failed=None: done(operation())

        try:
            window.record.preview_step()

            self.assertEqual(executed, [step])
            self.assertEqual(active, [(True, "record_preview"), (False,)])
            self.assertEqual(finished, [True])
        finally:
            self.close_window(window)


class WorkerAndFailureCaptureTests(unittest.TestCase):
    def test_failure_capture_uses_bound_session(self):
        image = np.zeros((12, 18, 3), dtype=np.uint8)
        messages = []
        page = SimpleNamespace(log_signal=SimpleNamespace(emit=messages.append))
        session = SimpleNamespace(screenshot=lambda: image)

        with tempfile.TemporaryDirectory() as directory, patch(
            "qt_workbench.APP_DIR", Path(directory)
        ):
            PlaybackPage.capture_failure_screen(
                page, Path("case.maa_job.json"), session
            )
            files = list((Path(directory) / "logs" / "failures").glob("*.png"))

        self.assertEqual(len(files), 1)
        self.assertTrue(any("\u5931\u8d25\u622a\u56fe" in message for message in messages))

    def test_close_waits_for_worker_and_finished_callback_rechecks_close(self):
        class FakeSignal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

            def emit(self):
                self.callback()

        class FakeWorker:
            def __init__(self):
                self.finished = FakeSignal()
                self.running = True

            def isRunning(self):
                return self.running

        closed = []
        worker = FakeWorker()
        owner = SimpleNamespace(
            workers=[], close_when_idle=True, execution_active=False,
            close=lambda: closed.append(True),
        )
        owner.finish_close_if_requested = lambda: Workbench.finish_close_if_requested(owner)

        Workbench.keep_worker(owner, worker)
        Workbench.finish_close_if_requested(owner)
        self.assertEqual(closed, [])

        worker.running = False
        worker.finished.emit()
        self.assertEqual(owner.workers, [])
        self.assertEqual(closed, [True])

if __name__ == "__main__":
    unittest.main()
