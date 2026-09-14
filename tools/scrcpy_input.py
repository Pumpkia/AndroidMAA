"""通过 scrcpy 投屏窗口发送点击（优先 --mouse=uhid）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.request
import zipfile


_PROCS: dict[str, subprocess.Popen] = {}
_EMBEDDED: dict[str, Any] = {}
_UPDATE_CHECKED = False
GITHUB_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
FALLBACK_TAG = "v3.2"
FALLBACK_URL = "https://github.com/Genymobile/scrcpy/releases/download/v3.2/scrcpy-win64-v3.2.zip"


def window_title(serial: str) -> str:
    return f"NnMaa-{serial}"


def map_device_to_client(
    x: int,
    y: int,
    device_width: int,
    device_height: int,
    client_width: int,
    client_height: int,
) -> tuple[int, int]:
    if min(device_width, device_height, client_width, client_height) <= 0:
        raise ValueError("分辨率无效")
    scale = min(client_width / device_width, client_height / device_height)
    content_w = device_width * scale
    content_h = device_height * scale
    offset_x = (client_width - content_w) / 2
    offset_y = (client_height - content_h) / 2
    return (
        int(offset_x + x * scale),
        int(offset_y + y * scale),
    )


def assistant_root() -> Path:
    """NnMaa 产品根目录。

    实现已收敛到 app_paths.assistant_root()（标记文件锚定，不依赖目录名）。
    本函数保留为薄封装，供本模块既有调用点（scrcpy_home / _mouse_click）使用。
    """

    from app_paths import assistant_root as _resolve_root

    return _resolve_root()


def _env(name: str, legacy: str = "") -> str:
    """读环境变量：NnMaa 新名优先，Qdd 旧名作为兼容兜底。"""

    value = os.environ.get(name, "").strip()
    if value:
        return value
    return os.environ.get(legacy, "").strip() if legacy else ""


def scrcpy_home() -> Path:
    override = _env("NNMAA_SCRCPY_HOME", "QDD_SCRCPY_HOME")
    if override:
        return Path(override)
    return assistant_root() / "scrcpy"


def resolve_scrcpy() -> Path | None:
    local = scrcpy_home() / ("scrcpy.exe" if os.name == "nt" else "scrcpy")
    if local.is_file():
        return local
    for name in ("scrcpy.exe", "scrcpy"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "scrcpy" / "scrcpy.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "scrcpy" / "scrcpy.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def available() -> bool:
    if _env("NNMAA_USE_SCRCPY", "QDD_USE_SCRCPY").strip().lower() in {"0", "false", "no"}:
        return False
    return os.name == "nt"


def version_from_tag(tag: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", tag or "")
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def fetch_latest_win64() -> tuple[str, str]:
    request = urllib.request.Request(
        GITHUB_API,
        headers={"User-Agent": "NnMaa-scrcpy", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    tag = str(payload.get("tag_name") or "")
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if "win64" in name and name.endswith(".zip") and url:
            return tag, url
    raise RuntimeError("GitHub 没有 Windows 64 位 scrcpy 包")


def download_scrcpy(url: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / ".scrcpy-download.zip"
    request = urllib.request.Request(url, headers={"User-Agent": "NnMaa-scrcpy"})
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            output.write(chunk)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)
    archive.unlink(missing_ok=True)
    exe = dest / "scrcpy.exe"
    if exe.is_file():
        return
    nested = [path for path in dest.iterdir() if path.is_dir() and (path / "scrcpy.exe").is_file()]
    if not nested:
        raise RuntimeError("解压后没有 scrcpy.exe")
    for item in nested[0].iterdir():
        target = dest / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
    shutil.rmtree(nested[0], ignore_errors=True)
    if not exe.is_file():
        raise RuntimeError("解压后没有 scrcpy.exe")


def ensure_installed() -> Path:
    global _UPDATE_CHECKED
    home = scrcpy_home()
    exe = home / "scrcpy.exe"
    remote_tag = ""
    remote_url = FALLBACK_URL
    try:
        remote_tag, remote_url = fetch_latest_win64()
    except Exception:
        remote_tag = FALLBACK_TAG
        remote_url = FALLBACK_URL
    remote = version_from_tag(remote_tag)
    if not exe.is_file():
        download_scrcpy(remote_url, home)
        _UPDATE_CHECKED = True
        return exe
    if not _UPDATE_CHECKED:
        _UPDATE_CHECKED = True
        local = read_scrcpy_version(exe)
        if remote > local:
            download_scrcpy(remote_url, home)
    return exe


def is_running(serial: str) -> bool:
    return bool(serial) and _find_hwnd(window_title(serial)) is not None


def tap(serial: str, x: int, y: int, device_width: int, device_height: int) -> bool:
    if not available():
        return False
    ensure_running(serial)
    return _click_window(serial, int(x), int(y), device_width, device_height)


def swipe(
    serial: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    device_width: int,
    device_height: int,
    duration_ms: int = 300,
) -> bool:
    if not available():
        return False
    ensure_running(serial)
    return _drag_window(
        serial, int(x1), int(y1), int(x2), int(y2), device_width, device_height, duration_ms
    )


def parse_scrcpy_version(text: str) -> tuple[int, int]:
    match = re.search(r"scrcpy\s+(\d+)\.(\d+)", text or "")
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def read_scrcpy_version(executable: Path) -> tuple[int, int]:
    result = subprocess.run(
        [str(executable), "-v"],
        capture_output=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    text = (result.stdout or b"").decode("utf-8", "replace") + (result.stderr or b"").decode("utf-8", "replace")
    return parse_scrcpy_version(text)


def launch_args(executable: Path, serial: str) -> list[str]:
    args = [
        str(executable),
        "--serial",
        serial,
        "--stay-awake",
        f"--window-title={window_title(serial)}",
    ]
    major, minor = read_scrcpy_version(executable)
    if (major, minor) >= (2, 0):
        args.extend(["--no-audio", "--window-borderless"])
    if (major, minor) >= (2, 4):
        args.extend(["--mouse=uhid", "--keyboard=uhid"])
    return args


def _adb_executable() -> Path:
    """与 _launch_env 相同的优先级解析 ADB，供设备状态预检使用。"""

    try:
        from app_paths import APP_PATHS

        adb = APP_PATHS.app_dir / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        if adb.is_file():
            return adb
    except Exception:
        pass
    local = scrcpy_home() / ("adb.exe" if os.name == "nt" else "adb")
    if local.is_file():
        return local
    found = shutil.which("adb")
    return Path(found) if found else local


def _assert_device_ready(serial: str) -> None:
    """启动 scrcpy 前预检设备状态，给出比「窗口超时」精确得多的错误。"""

    adb = _adb_executable()
    try:
        result = subprocess.run(
            [str(adb), "-s", serial, "get-state"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        return  # adb 本身缺失时交给 scrcpy 自己报错
    except subprocess.TimeoutExpired:
        raise RuntimeError("ADB 响应超时（adb server 可能正在重启），请稍后重试")
    state = (result.stdout or b"").decode("utf-8", "replace").strip()
    err = (result.stderr or b"").decode("utf-8", "replace").strip()
    if state == "device":
        return
    if state == "unauthorized":
        raise RuntimeError("设备未授权 USB 调试：请在手机上允许「USB 调试授权」后重试")
    if state == "offline":
        raise RuntimeError("设备处于 offline 状态：请重新插拔数据线（或在手机上撤销并重新授权 USB 调试）")
    if "not found" in err.lower() or "not found" in state.lower():
        raise RuntimeError(f"ADB 未找到设备 {serial}：请检查数据线连接与 USB 调试开关")
    # 其他未知输出不拦，交给 scrcpy 的真实报错


def _launch_env() -> dict[str, str]:
    env = os.environ.copy()
    try:
        from app_paths import APP_PATHS

        adb = APP_PATHS.app_dir / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        if adb.is_file():
            env["ADB"] = str(adb)
            env["PATH"] = str(adb.parent) + os.pathsep + env.get("PATH", "")
    except Exception:
        pass
    return env


def _drain_stderr(stream: Any, sink: list[str]) -> None:
    """后台线程持续收集 scrcpy 的 stderr，只保留最后 30 行用于诊断。"""

    try:
        for line in iter(stream.readline, b""):
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                sink.append(text)
                del sink[:-30]
    except Exception:
        pass


def ensure_running(serial: str) -> None:
    if _find_hwnd(window_title(serial)):
        return
    executable = ensure_installed()
    if executable is None or not executable.is_file():
        raise RuntimeError("scrcpy 下载或安装失败")
    # 清理上次超时遗留的僵尸 scrcpy 进程，避免它占住设备导致重试永远失败
    stale = _PROCS.pop(serial, None)
    if stale is not None and stale.poll() is None:
        stale.terminate()
        try:
            stale.wait(timeout=3)
        except subprocess.TimeoutExpired:
            stale.kill()
        time.sleep(0.3)
    _assert_device_ready(serial)
    args = launch_args(executable, serial)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_launch_env(),
    )
    _PROCS[serial] = process
    stderr_tail: list[str] = []
    threading.Thread(target=_drain_stderr, args=(process.stderr, stderr_tail), daemon=True).start()
    deadline = time.time() + 25
    while time.time() < deadline:
        if process.poll() is not None:
            detail = "；".join(stderr_tail[-3:]) or "scrcpy 进程已退出"
            _PROCS.pop(serial, None)
            raise RuntimeError(detail[:400])
        if _find_hwnd(window_title(serial)):
            time.sleep(0.4)
            return
        time.sleep(0.25)
    # 超时：杀掉卡住的进程（否则它会一直占着设备），并带上 stderr 诊断信息
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    _PROCS.pop(serial, None)
    detail = "；".join(stderr_tail[-3:])
    raise RuntimeError("scrcpy 窗口超时未出现" + (f"（scrcpy 输出：{detail[:300]}）" if detail else ""))


def embed(serial: str, parent_hwnd: int, width: int, height: int) -> bool:
    if os.name != "nt":
        return False
    ensure_running(serial)
    hwnd = _find_hwnd(window_title(serial))
    if not hwnd:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    gwl_style = -16
    ws_child = 0x40000000
    ws_visible = 0x10000000
    ws_popup = 0x80000000
    ws_caption = 0x00C00000
    ws_thickframe = 0x00040000
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    style = get_long(hwnd, gwl_style)
    style = (style | ws_child | ws_visible) & ~ws_popup & ~ws_caption & ~ws_thickframe
    set_long(hwnd, gwl_style, style)
    # 重新应用窗口样式：改完 GWL_STYLE 后必须发 SWP_FRAMECHANGED，
    # 否则 WS_CHILD 不会真正生效，子窗口处于「样式不一致」状态，鼠标/渲染都会出怪事。
    swp_framechanged = 0x0020
    swp_nomove = 0x0002
    swp_nosize = 0x0001
    swp_nozorder = 0x0004
    swp_noactivate = 0x0010
    user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        swp_framechanged | swp_nomove | swp_nosize | swp_nozorder | swp_noactivate,
    )
    user32.SetParent(hwnd, int(parent_hwnd))
    user32.MoveWindow(hwnd, 0, 0, max(1, int(width)), max(1, int(height)), True)
    _EMBEDDED[serial] = hwnd
    return True


def resize_embedded(serial: str, width: int, height: int) -> None:
    if os.name != "nt":
        return
    import ctypes

    hwnd = _EMBEDDED.get(serial) or _find_hwnd(window_title(serial))
    if not hwnd:
        return
    ctypes.windll.user32.MoveWindow(hwnd, 0, 0, max(1, int(width)), max(1, int(height)), True)


def stop(serial: str) -> None:
    if not serial:
        return
    _EMBEDDED.pop(serial, None)
    process = _PROCS.pop(serial, None)
    if process is not None and process.poll() is None:
        process.terminate()


def _find_hwnd(title: str) -> Any:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buffer = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buffer, length)
        if buffer.value == title or title in buffer.value:
            found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def _client_size(hwnd) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _client_to_screen(hwnd, x: int, y: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT(x, y)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def _foreground(hwnd) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)


def _mouse_click(screen_x: int, screen_y: int) -> None:
    src = assistant_root() / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from dauto.input import left_click

        left_click(int(screen_x), int(screen_y))
        return
    except Exception:
        pass
    _mouse_down(screen_x, screen_y)
    time.sleep(0.04)
    _mouse_up()


def _mouse_down(screen_x: int, screen_y: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(screen_x), int(screen_y))
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        )

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("mi", MOUSEINPUT))

    payload = INPUT(0, MOUSEINPUT(0, 0, 0, 0x0002, 0, None))
    user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(payload))


def _mouse_up() -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        )

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("mi", MOUSEINPUT))

    payload = INPUT(0, MOUSEINPUT(0, 0, 0, 0x0004, 0, None))
    user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(payload))


def _press_at(screen_x: int, screen_y: int) -> None:
    """把光标移到 (逻辑像素) 坐标并按下左键。

    全程使用逻辑像素：Qt 进程是 DPI 感知的，``ClientToScreen`` / ``SetCursorPos``
    都返回/接受逻辑像素，而 ``SendInput(MOUSEEVENTF_ABSOLUTE)`` 用的是物理像素——
    两者混用正是「点偏位 → 误触返回/主页 → 真机 App 退出」的根因。这里统一走
    ``SetCursorPos`` + 相对 ``mouse_down/up``，不再碰绝对坐标，DPI 缩放下也准。
    """
    import ctypes
    ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
    time.sleep(0.012)
    _mouse_down(int(screen_x), int(screen_y))


def _release() -> None:
    _mouse_up()


def _click_at_screen(screen_x: int, screen_y: int) -> None:
    _press_at(screen_x, screen_y)
    time.sleep(0.04)
    _release()


def _click_window(serial: str, x: int, y: int, device_width: int, device_height: int) -> bool:
    hwnd = _find_hwnd(window_title(serial))
    if not hwnd:
        return False
    client_w, client_h = _client_size(hwnd)
    cx, cy = map_device_to_client(x, y, device_width, device_height, client_w, client_h)
    sx, sy = _client_to_screen(hwnd, cx, cy)
    # 不再 foreground 子窗口（子窗口 SetForegroundWindow 本就失败），
    # 直接落在计算出的屏幕坐标上即可，避免抢焦点把工作台顶到前台。
    _click_at_screen(sx, sy)
    return True


def _drag_window(
    serial: str,
    x1: int, y1: int,
    x2: int, y2: int,
    device_width: int,
    device_height: int,
    duration_ms: int,
) -> bool:
    hwnd = _find_hwnd(window_title(serial))
    if not hwnd:
        return False
    client_w, client_h = _client_size(hwnd)
    a = map_device_to_client(x1, y1, device_width, device_height, client_w, client_h)
    b = map_device_to_client(x2, y2, device_width, device_height, client_w, client_h)
    s1 = _client_to_screen(hwnd, *a)
    s2 = _client_to_screen(hwnd, *b)
    _press_at(*s1)
    steps = max(5, int(duration_ms / 20))
    for index in range(1, steps + 1):
        px = int(s1[0] + (s2[0] - s1[0]) * index / steps)
        py = int(s1[1] + (s2[1] - s1[1]) * index / steps)
        ctypes.windll.user32.SetCursorPos(px, py)
        time.sleep(duration_ms / steps / 1000)
    _release()
    return True
