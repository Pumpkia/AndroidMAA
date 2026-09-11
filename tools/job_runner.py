"""MaaFramework runtime used by the visual job editor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Callable

from maa.context import ContextEventSink
from maa.controller import AdbController
from maa.define import MaaAdbInputMethodEnum
from maa.resource import Resource
from maa.tasker import Tasker, TaskerEventSink
from maa.toolkit import Toolkit

from job_model import JobDocument, safe_name


LogCallback = Callable[[str], None]


EVENT_TEXT = {
    "Tasker.Task.Starting": "作业开始",
    "Tasker.Task.Succeeded": "作业执行成功",
    "Tasker.Task.Failed": "作业执行失败",
    "Tasker.Task.Stopped": "作业已停止",
    "Node.Recognition.Starting": "开始识别",
    "Node.Recognition.Succeeded": "识别成功",
    "Node.Recognition.Failed": "识别失败",
    "Node.Action.Starting": "开始动作",
    "Node.Action.Succeeded": "动作成功",
    "Node.Action.Failed": "动作失败",
}


def format_event(message: str, details: dict) -> str:
    title = EVENT_TEXT.get(message, message)
    node = details.get("name") or details.get("node_name") or details.get("entry")
    return f"{title}：{node}" if node else title


class EditorTaskerSink(TaskerEventSink):
    def __init__(self, emit: LogCallback) -> None:
        self.emit = emit

    def _on_raw_notification(self, _handle, message: str, details: dict) -> None:
        self.emit(format_event(message, details))


class EditorContextSink(ContextEventSink):
    def __init__(self, emit: LogCallback) -> None:
        self.emit = emit

    def _on_raw_notification(self, _handle, message: str, details: dict) -> None:
        if message.startswith("Node."):
            self.emit(format_event(message, details))


MAA_COORDINATE_SHORT_SIDE = 720


def controller_runtime_device_size(controller) -> list[int]:
    if not controller.set_screenshot_target_short_side(MAA_COORDINATE_SHORT_SIDE):
        raise RuntimeError("Failed to configure Maa screenshot coordinate size")
    screenshot_job = controller.post_screencap().wait()
    if not screenshot_job.succeeded:
        raise RuntimeError("Failed to capture the target device screen")
    image = screenshot_job.get()
    shape = getattr(image, "shape", ())
    if len(shape) < 2 or int(shape[0]) <= 0 or int(shape[1]) <= 0:
        raise RuntimeError("Maa returned an invalid target device screenshot")
    return [int(shape[1]), int(shape[0])]


class MaaJobRunner:
    def __init__(
        self,
        app_dir: Path,
        assets_dir: Path,
        jobs_dir: Path,
        user_resource_dir: Path | None = None,
        user_data_dir: Path | None = None,
    ) -> None:
        self.app_dir = app_dir
        self.assets_dir = assets_dir
        self.jobs_dir = jobs_dir
        self.user_resource_dir = Path(user_resource_dir) if user_resource_dir is not None else None
        self.user_data_dir = (
            Path(user_data_dir) if user_data_dir is not None
            else Path(jobs_dir).parent
        )
        self._tasker: Tasker | None = None
        self._tasker_sink: EditorTaskerSink | None = None
        self._context_sink: EditorContextSink | None = None
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._run_active = False
        self._cancel_requested = threading.Event()
        self.module_validate = None

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._tasker and self._tasker.running)

    def _resource_directories(self) -> list[Path]:
        directories = [self.assets_dir / "resource"]
        if self.user_resource_dir is not None:
            directories.append(self.user_resource_dir)

        unique = []
        seen = set()
        for directory in directories:
            identity = os.path.normcase(str(directory.resolve(strict=False)))
            if identity not in seen:
                seen.add(identity)
                unique.append(directory)
        return unique

    def _post_resource_bundles(self, resource):
        last_job = None
        for directory in self._resource_directories():
            last_job = resource.post_bundle(directory).wait()
            if not last_job.succeeded:
                return last_job
        return last_job

    def _load_default_config(self) -> dict:
        config_path = self.assets_dir / "config" / "maa_option.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RuntimeError(f"Maa default configuration is missing: {config_path}") from error
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Maa default configuration is invalid: {config_path}") from error

        if not isinstance(config, dict):
            raise RuntimeError(f"Maa default configuration must be a JSON object: {config_path}")
        return config

    def run(self, document: JobDocument, serial: str, emit: LogCallback) -> bool:
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError("ADB serial is required")
        if isinstance(document, JobDocument):
            prerequisites = document.resolve_prerequisites(self.jobs_dir) if document.prerequisites else []
            documents = [document, *prerequisites]
            errors: list[str] = []
            for item in documents:
                errors.extend(item.validate())
                if callable(self.module_validate):
                    errors.extend(self.module_validate(item) or [])
            if errors:
                raise ValueError("\n".join(errors))
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("A Maa job is already running")
        with self._lock:
            self._run_active = True
            self._cancel_requested.clear()
        try:
            return self._run_once(document, serial, emit)
        finally:
            with self._lock:
                self._run_active = False
                self._cancel_requested.clear()
            self._run_lock.release()

    def _run_once(self, document: JobDocument, serial: str, emit: LogCallback) -> bool:
        with self._lock:
            if self._tasker and self._tasker.running:
                raise RuntimeError("已有作业正在执行")

        default_config = self._load_default_config()
        Toolkit.init_option(self.user_data_dir, default_config)
        adb_path = self._adb_path()
        devices = Toolkit.find_adb_devices(adb_path if adb_path.exists() else None)
        device = next((item for item in devices if item.address == serial), None)
        if device is None:
            raise RuntimeError(f"找不到 ADB 设备: {serial}")

        emit(f"连接设备：{device.name} ({device.address})")
        emit("输入方式：ADB Shell（兼容模式）")
        controller_args = {
            "adb_path": device.adb_path,
            "address": device.address,
            "screencap_methods": device.screencap_methods,
            # Maatouch may report success even when Android receives no text.
            "input_methods": int(MaaAdbInputMethodEnum.AdbShell),
            "config": device.config,
        }
        packaged_agent = self.app_dir / "_internal" / "MaaAgentBinary"
        if packaged_agent.exists():
            controller_args["agent_path"] = packaged_agent
        controller = AdbController(**controller_args)
        connection = controller.post_connection().wait()
        if not connection.succeeded:
            raise RuntimeError("Maa ADB 控制器连接失败")

        emit("加载识别资源与模板")
        runtime_device_size = controller_runtime_device_size(controller)
        emit(f"Maa coordinates: {runtime_device_size[0]} x {runtime_device_size[1]}")

        resource = Resource()
        resource_job = self._post_resource_bundles(resource)
        if not resource_job.succeeded:
            raise RuntimeError("Maa 资源加载失败")

        prerequisites = document.resolve_prerequisites(self.jobs_dir) if document.prerequisites else []
        pipeline = document.to_pipeline(
            prerequisites,
            runtime_device_size=runtime_device_size,
        )
        entry = safe_name(document.name, "NikkiJob")

        tasker = Tasker()
        tasker_sink = EditorTaskerSink(emit)
        context_sink = EditorContextSink(emit)
        tasker.add_sink(tasker_sink)
        tasker.add_context_sink(context_sink)
        tasker.bind(resource, controller)
        if not tasker.inited:
            raise RuntimeError("Maa Tasker 初始化失败")

        with self._lock:
            self._tasker = tasker
            self._tasker_sink = tasker_sink
            self._context_sink = context_sink
            cancelled = self._cancel_requested.is_set()
        if cancelled:
            tasker.post_stop().wait()
            return False
        try:
            emit(f"执行入口：{entry}")
            job = tasker.post_task(entry, pipeline)
            job.wait()
            return job.succeeded
        finally:
            with self._lock:
                self._tasker = None
                self._tasker_sink = None
                self._context_sink = None

    def stop(self, emit: LogCallback) -> bool:
        with self._lock:
            active = self._run_active
            if active:
                self._cancel_requested.set()
            tasker = self._tasker
        if not active:
            return False
        if tasker is None:
            emit("Stop requested; waiting for Maa setup to finish")
            return True
        if not tasker.running:
            return True
        emit("正在停止作业…")
        tasker.post_stop().wait()
        return True

    def _adb_path(self) -> Path:
        names = ("adb.exe", "adb") if os.name == "nt" else ("adb", "adb.exe")
        for name in names:
            candidate = self.app_dir / "platform-tools" / name
            if candidate.exists():
                return candidate
        return Path("adb")
