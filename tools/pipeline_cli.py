"""NnMaa 无头流水线入口（`NnMaa.exe --run`）。

调用链与图形工作台共用同一套运行时参数：
加载 MaaFramework 资源 → 连接 ADB 设备 → 执行指定的 Pipeline 入口节点。

取代了旧的根目录 `run.py`。旧脚本调用 `Resource.load()`，该接口在 MaaFw 5.x
中已不存在，因此它早已无法运行；此处改为 5.x 的 `Resource.post_bundle()`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from maa.controller import AdbController
from maa.define import MaaAdbInputMethodEnum
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

from app_paths import APP_PATHS
from job_runner import EditorTaskerSink, MAA_COORDINATE_SHORT_SIDE


DEFAULT_ENTRY = "StartNikki"


def attach_parent_console() -> None:
    """打包版是窗口程序（console=False），执行 CLI 时主动挂到调用方控制台。

    从 cmd / PowerShell 调用时能直接看到输出；双击启动时没有父控制台，静默跳过。
    """

    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import ctypes

        if not ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return
        # 不指定编码，沿用系统区域默认（中文 Windows = cp936），与当前控制台代码页一致。
        sys.stdout = open("CONOUT$", "w", buffering=1)
        sys.stderr = open("CONOUT$", "w", buffering=1)
    except Exception:
        # 控制台不可用时不影响程序继续运行，只是没有输出。
        pass


def _emit(text: str) -> None:
    print(f"[NnMaa] {text}", flush=True)


def _adb_path(app_dir: Path) -> Path:
    names = ("adb.exe", "adb") if os.name == "nt" else ("adb", "adb.exe")
    for name in names:
        candidate = app_dir / "platform-tools" / name
        if candidate.exists():
            return candidate
    return Path("adb")


def _load_default_config(assets_dir: Path) -> dict | None:
    config_path = assets_dir / "config" / "maa_option.json"
    if not config_path.is_file():
        return None
    import json

    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_pipeline(entry: str = DEFAULT_ENTRY, serial: str | None = None) -> int:
    """执行一个 Pipeline 入口节点。返回进程退出码，0 表示成功。"""

    app_dir = APP_PATHS.app_dir
    assets_dir = APP_PATHS.assets_dir
    resource_dir = assets_dir / "resource"

    if not resource_dir.is_dir():
        _emit(f"资源目录不存在：{resource_dir}")
        return 2

    default_config = _load_default_config(assets_dir)
    if default_config is None:
        Toolkit.init_option(APP_PATHS.data_dir)
    else:
        Toolkit.init_option(APP_PATHS.data_dir, default_config)

    adb_path = _adb_path(app_dir)
    devices = Toolkit.find_adb_devices(adb_path if adb_path.exists() else None)
    if not devices:
        _emit("未找到 ADB 设备。")
        _emit("请确认设备已连接、已开启 USB 调试并完成授权，")
        _emit("可用 adb devices 确认设备状态为 device。")
        return 3

    if serial:
        device = next((item for item in devices if item.address == serial), None)
        if device is None:
            _emit(f"找不到指定设备：{serial}")
            _emit("当前可用设备：" + "，".join(item.address for item in devices))
            return 3
    else:
        device = devices[0]

    _emit(f"连接设备：{device.name} ({device.address})")
    controller_args = {
        "adb_path": device.adb_path,
        "address": device.address,
        "screencap_methods": device.screencap_methods,
        # Maatouch 可能报成功但 Android 收不到文字输入，与工作台保持一致走 AdbShell。
        "input_methods": int(MaaAdbInputMethodEnum.AdbShell),
        "config": device.config,
    }
    packaged_agent = app_dir / "_internal" / "MaaAgentBinary"
    if packaged_agent.exists():
        controller_args["agent_path"] = packaged_agent

    controller = AdbController(**controller_args)
    if not controller.post_connection().wait().succeeded:
        _emit("ADB 控制器连接失败。")
        return 4

    if not controller.set_screenshot_target_short_side(MAA_COORDINATE_SHORT_SIDE):
        _emit("无法配置 Maa 截图坐标尺寸。")
        return 4

    _emit(f"加载资源：{resource_dir}")
    resource = Resource()
    if not resource.post_bundle(resource_dir).wait().succeeded:
        _emit("Maa 资源加载失败。")
        return 2

    sink = EditorTaskerSink(_emit)
    tasker = Tasker()
    tasker.add_sink(sink)
    tasker.bind(resource, controller)
    if not tasker.inited:
        _emit("Maa Tasker 初始化失败。")
        return 4

    _emit(f"执行任务：{entry}")
    try:
        job = tasker.post_task(entry)
        job.wait()
        succeeded = bool(job.succeeded)
    finally:
        tasker.post_stop().wait()

    if succeeded:
        _emit("任务成功。")
        return 0
    _emit("任务失败。")
    return 5
