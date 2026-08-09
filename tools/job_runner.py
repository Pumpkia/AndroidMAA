"""MaaFramework runtime used by the visual job editor."""

from __future__ import annotations

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


class MaaJobRunner:
    def __init__(self, app_dir: Path, assets_dir: Path, jobs_dir: Path) -> None:
        self.app_dir = app_dir
        self.assets_dir = assets_dir
        self.jobs_dir = jobs_dir
        self._tasker: Tasker | None = None
        self._tasker_sink: EditorTaskerSink | None = None
        self._context_sink: EditorContextSink | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._tasker and self._tasker.running)

    def run(self, document: JobDocument, serial: str, emit: LogCallback) -> bool:
        with self._lock:
            if self._tasker and self._tasker.running:
                raise RuntimeError("已有作业正在执行")

        Toolkit.init_option(self.assets_dir)
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
        resource = Resource()
        resource_job = resource.post_bundle(self.assets_dir / "resource").wait()
        if not resource_job.succeeded:
            raise RuntimeError("Maa 资源加载失败")

        prerequisites = document.resolve_prerequisites(self.jobs_dir) if document.prerequisites else []
        pipeline = document.to_pipeline(prerequisites)
        entry = safe_name(document.name, "QQJob")

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
            tasker = self._tasker
        if tasker is None or not tasker.running:
            return False
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
