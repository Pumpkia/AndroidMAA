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
_OVERLAY_READY: set[str] = set()
_LAST_PLACE: dict[str, tuple[int, int, int, int]] = {}
_UPDATE_CHECKED = False
GITHUB_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
FALLBACK_TAG = "v3.2"
FALLBACK_URL = "https://github.com/Genymobile/scrcpy/releases/download/v3.2/scrcpy-win64-v3.2.zip"


def window_title(serial: str) -> str:
    return f"NnMaa-{serial}"


_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CHILD = 0x40000000
_WS_VISIBLE = 0x10000000
_WS_CLIPSIBLINGS = 0x04000000
_WS_CLIPCHILDREN = 0x02000000
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_POPUP = 0x80000000
_WS_SYSMENU = 0x00080000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_WINDOWEDGE = 0x00000100
_WS_EX_DLGMODALFRAME = 0x00000001
_WS_EX_NOACTIVATE = 0x08000000
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_SWP_NOCOPYBITS = 0x0100
_SW_SHOW = 5
_SW_HIDE = 0
_GWLP_HWNDPARENT = -8
_WM_CLOSE = 0x0010


def child_window_style(style: int) -> int:
    drop = _WS_POPUP | _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
    value = (int(style) & 0xFFFFFFFF) | _WS_CHILD | _WS_VISIBLE | _WS_CLIPSIBLINGS | _WS_CLIPCHILDREN
    return value & ~drop & 0xFFFFFFFF


def child_window_exstyle(exstyle: int) -> int:
    drop = _WS_EX_APPWINDOW | _WS_EX_WINDOWEDGE | _WS_EX_DLGMODALFRAME
    return int(exstyle) & 0xFFFFFFFF & ~drop


def overlay_window_style(style: int) -> int:
    drop = _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX | _WS_CHILD
    return (int(style) & 0xFFFFFFFF & ~drop) | _WS_POPUP | _WS_VISIBLE


def overlay_window_exstyle(exstyle: int) -> int:
    return child_window_exstyle(exstyle)


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
    if not serial:
        return False
    if _hwnd_for(serial):
        return True
    process = _PROCS.get(serial)
    return process is not None and process.poll() is None


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


def launch_args(
    executable: Path,
    serial: str,
    width: int = 0,
    height: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> list[str]:
    args = [
        str(executable),
        "--serial",
        serial,
        "--stay-awake",
        "--no-audio",
        "--window-borderless",
        f"--window-title={window_title(serial)}",
    ]
    if x is not None and y is not None:
        args.extend([f"--window-x={int(x)}", f"--window-y={int(y)}"])
    if int(width) > 0 and int(height) > 0:
        args.extend([f"--window-width={int(width)}", f"--window-height={int(height)}"])
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


def ensure_running(
    serial: str,
    width: int = 0,
    height: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> None:
    process = _PROCS.get(serial)
    alive = process is not None and process.poll() is None
    hwnd = _hwnd_for(serial)
    if hwnd and alive:
        _hide_pid_consoles(process.pid)
        return
    if hwnd and not alive:
        _close_hwnd(hwnd)
        _EMBEDDED.pop(serial, None)
    if process is not None and process.poll() is None:
        deadline = time.time() + 8
        while time.time() < deadline:
            if _hwnd_for(serial):
                _hide_pid_consoles(process.pid)
                return
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if _hwnd_for(serial):
            _hide_pid_consoles(process.pid)
            return
    executable = ensure_installed()
    if executable is None or not executable.is_file():
        raise RuntimeError("scrcpy 下载或安装失败")
    stale = _PROCS.pop(serial, None)
    if stale is not None and stale.poll() is None:
        stale.terminate()
        try:
            stale.wait(timeout=3)
        except subprocess.TimeoutExpired:
            stale.kill()
        time.sleep(0.3)
    _EMBEDDED.pop(serial, None)
    leftover = _find_top_level(window_title(serial))
    if leftover:
        _close_hwnd(leftover)
    _assert_device_ready(serial)
    args = launch_args(executable, serial, width, height, x, y)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_launch_env(),
        creationflags=flags,
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
        _hide_pid_consoles(process.pid)
        if _hwnd_for(serial):
            time.sleep(0.4)
            _hide_pid_consoles(process.pid)
            _keep_one_window(serial)
            return
        time.sleep(0.25)
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    _PROCS.pop(serial, None)
    detail = "；".join(stderr_tail[-3:])
    raise RuntimeError("scrcpy 窗口超时未出现" + (f"（scrcpy 输出：{detail[:300]}）" if detail else ""))


def embed(serial: str, parent_hwnd: int, width: int, height: int, launch: bool = True) -> bool:
    if os.name != "nt":
        return False
    parent = _as_hwnd(parent_hwnd)
    if not parent:
        return False
    if launch:
        ensure_running(serial, width, height)
    hwnd = _hwnd_for(serial, parent)
    if not hwnd:
        return False
    return _reparent(serial, hwnd, parent, width, height)


def resize_embedded(serial: str, width: int, height: int) -> None:
    if os.name != "nt":
        return
    hwnd = _hwnd_for(serial)
    if not hwnd:
        return
    _user32().MoveWindow(hwnd, 0, 0, max(1, int(width)), max(1, int(height)), True)


def stop(serial: str) -> None:
    if not serial:
        return
    title = window_title(serial)
    pids: set[int] = set()
    process = _PROCS.pop(serial, None)
    if process is not None and process.poll() is None:
        pids.add(process.pid)
    cached = _as_hwnd(_EMBEDDED.pop(serial, None))
    if cached:
        pid = _pid_of(cached)
        if pid:
            pids.add(pid)
        _close_hwnd(cached)
    for hwnd in _find_all_hwnds(title):
        pid = _pid_of(hwnd)
        if pid:
            pids.add(pid)
        _close_hwnd(hwnd)
    for pid in pids:
        _terminate_pid(pid)
    time.sleep(0.25)
    for hwnd in _find_all_hwnds(title):
        pid = _pid_of(hwnd)
        _close_hwnd(hwnd)
        if pid:
            _terminate_pid(pid)
    _OVERLAY_READY.discard(serial)
    _LAST_PLACE.pop(serial, None)


def host_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    if os.name != "nt" or not hwnd:
        return (0, 0, 0, 0)
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def place_over_host(
    serial: str,
    host_hwnd: int,
    owner_hwnd: int = 0,
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    force: bool = False,
) -> bool:
    gx, gy, gw, gh = host_screen_rect(host_hwnd)
    if int(width) * int(height) > gw * gh:
        gx, gy, gw, gh = int(x), int(y), int(width), int(height)
    if gw <= 1 or gh <= 1:
        return False
    return place_over(serial, gx, gy, gw, gh, owner_hwnd, force=force)


def place_over(
    serial: str,
    x: int,
    y: int,
    width: int,
    height: int,
    owner_hwnd: int = 0,
    force: bool = False,
) -> bool:
    if os.name != "nt" or not serial:
        return False
    hwnd = _keep_one_window(serial)
    if not hwnd:
        return False
    rect = (int(x), int(y), max(1, int(width)), max(1, int(height)))
    owner = _as_hwnd(owner_hwnd)
    if not force and _LAST_PLACE.get(serial) == rect:
        release_pointer_if_left(serial)
        return True
    user32 = _user32()
    get_long, set_long = _style_funcs(user32)
    if serial not in _OVERLAY_READY:
        if _as_hwnd(user32.GetParent(hwnd)):
            user32.SetParent(hwnd, 0)
        set_long(hwnd, _GWL_STYLE, overlay_window_style(get_long(hwnd, _GWL_STYLE)))
        set_long(hwnd, _GWL_EXSTYLE, overlay_window_exstyle(get_long(hwnd, _GWL_EXSTYLE)))
        if owner:
            set_long(hwnd, _GWLP_HWNDPARENT, owner)
        _OVERLAY_READY.add(serial)
    flags = _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_SHOWWINDOW
    if force:
        flags |= _SWP_NOCOPYBITS | _SWP_FRAMECHANGED
    user32.SetWindowPos(hwnd, 0, rect[0], rect[1], rect[2], rect[3], flags)
    user32.MoveWindow(hwnd, rect[0], rect[1], rect[2], rect[3], True)
    _LAST_PLACE[serial] = rect
    _EMBEDDED[serial] = hwnd
    process = _PROCS.get(serial)
    if process is not None and process.poll() is None:
        _hide_pid_consoles(process.pid)
    return True


def release_pointer_if_left(serial: str) -> None:
    if os.name != "nt" or not serial:
        return
    import ctypes
    from ctypes import wintypes

    hwnd = _as_hwnd(_EMBEDDED.get(serial)) or _hwnd_for(serial)
    if not hwnd:
        return
    user32 = _user32()
    left, top, width, height = host_screen_rect(hwnd)
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return
    if left <= point.x < left + width and top <= point.y < top + height:
        return
    captured = _as_hwnd(user32.GetCapture())
    if captured == hwnd:
        user32.ReleaseCapture()
    user32.ClipCursor(None)


def set_window_visible(serial: str, visible: bool) -> None:
    hwnd = _hwnd_for(serial)
    if not hwnd:
        return
    _user32().ShowWindow(hwnd, _SW_SHOW if visible else _SW_HIDE)


def _as_hwnd(value: Any) -> int:
    if not value:
        return 0
    if isinstance(value, int):
        return value
    raw = getattr(value, "value", value)
    if not raw:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


_USER32 = None
_ENUM_PROC = None


def _user32():
    global _USER32, _ENUM_PROC
    import ctypes
    from ctypes import wintypes

    if _USER32 is not None:
        return _USER32
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ptr = ctypes.c_ssize_t
    hwnd = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = hwnd
    user32.SetParent.argtypes = [hwnd, hwnd]
    user32.SetParent.restype = hwnd
    user32.GetParent.argtypes = [hwnd]
    user32.GetParent.restype = hwnd
    user32.IsWindow.argtypes = [hwnd]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [hwnd]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.MoveWindow.argtypes = [hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    user32.MoveWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [hwnd]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [hwnd, wintypes.LPRECT]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [hwnd, wintypes.LPRECT]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.ClipCursor.argtypes = [wintypes.LPRECT]
    user32.ClipCursor.restype = wintypes.BOOL
    user32.GetCapture.argtypes = []
    user32.GetCapture.restype = hwnd
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = hwnd
    user32.ClientToScreen.argtypes = [hwnd, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [hwnd]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.PostMessageW.argtypes = [hwnd, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ptr
        user32.SetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int, ptr]
        user32.SetWindowLongPtrW.restype = ptr
    user32.GetWindowLongW.argtypes = [hwnd, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [hwnd, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, hwnd, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [hwnd, enum_proc, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    _ENUM_PROC = enum_proc
    _USER32 = user32
    return user32


def _style_funcs(user32):
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
    return user32.GetWindowLongW, user32.SetWindowLongW


def _window_title(hwnd: int) -> str:
    import ctypes

    user32 = _user32()
    length = user32.GetWindowTextLengthW(hwnd) + 1
    if length <= 1:
        return ""
    buffer = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buffer, length)
    return buffer.value or ""


def _title_matches(text: str, title: str) -> bool:
    return bool(text) and (text == title or title in text)


def _enum_proc():
    _user32()
    return _ENUM_PROC


def _window_class(hwnd: int) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(hwnd, buffer, 256)
    return buffer.value or ""


def _close_hwnd(hwnd: int) -> None:
    if not hwnd:
        return
    user32 = _user32()
    user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    user32.ShowWindow(hwnd, _SW_HIDE)


def _hide_pid_consoles(pid: int) -> None:
    if os.name != "nt" or pid <= 0:
        return
    import ctypes
    from ctypes import wintypes

    user32 = _user32()

    @_enum_proc()
    def callback(hwnd, _lparam):
        handle = _as_hwnd(hwnd)
        proc_id = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(handle, ctypes.byref(proc_id))
        if proc_id.value == pid and _window_class(handle) == "ConsoleWindowClass":
            user32.ShowWindow(handle, _SW_HIDE)
        return True

    user32.EnumWindows(callback, 0)


def _find_top_level(title: str) -> int:
    if os.name != "nt":
        return 0
    user32 = _user32()
    for cls in ("SDL_app", None):
        hwnd = _as_hwnd(user32.FindWindowW(cls, title))
        if hwnd and _window_class(hwnd) != "ConsoleWindowClass":
            return hwnd
    found: list[int] = []

    @_enum_proc()
    def callback(hwnd, _lparam):
        handle = _as_hwnd(hwnd)
        if handle and _window_class(handle) != "ConsoleWindowClass" and _title_matches(_window_title(handle), title):
            found.append(handle)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def _pid_of(hwnd: int) -> int:
    if not hwnd:
        return 0
    import ctypes
    from ctypes import wintypes

    proc_id = wintypes.DWORD(0)
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
    return int(proc_id.value)


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F", "/T"],
        capture_output=True,
        creationflags=flags,
        timeout=5,
    )


def _find_all_hwnds(title: str) -> list[int]:
    if os.name != "nt" or not title:
        return []
    user32 = _user32()
    found: list[int] = []
    seen: set[int] = set()

    def consider(handle: int) -> None:
        if not handle or handle in seen:
            return
        if _window_class(handle) == "ConsoleWindowClass":
            return
        if _title_matches(_window_title(handle), title):
            seen.add(handle)
            found.append(handle)

    @_enum_proc()
    def on_child(hwnd, _lparam):
        consider(_as_hwnd(hwnd))
        return True

    @_enum_proc()
    def on_top(hwnd, _lparam):
        handle = _as_hwnd(hwnd)
        consider(handle)
        user32.EnumChildWindows(handle, on_child, 0)
        return True

    user32.EnumWindows(on_top, 0)
    return found


def _keep_one_window(serial: str) -> int:
    matches = _find_all_hwnds(window_title(serial))
    if not matches:
        _EMBEDDED.pop(serial, None)
        return 0
    cached = _as_hwnd(_EMBEDDED.get(serial))
    keep = cached if cached in matches else matches[0]
    keep_pid = _pid_of(keep)
    for extra in matches:
        if extra == keep:
            continue
        extra_pid = _pid_of(extra)
        _close_hwnd(extra)
        if extra_pid and extra_pid != keep_pid:
            _terminate_pid(extra_pid)
    _EMBEDDED[serial] = keep
    return keep


def _find_by_pid(pid: int, title: str) -> int:
    if os.name != "nt" or pid <= 0:
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    found: list[int] = []

    @_enum_proc()
    def callback(hwnd, _lparam):
        handle = _as_hwnd(hwnd)
        proc_id = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(handle, ctypes.byref(proc_id))
        if (
            proc_id.value == pid
            and _window_class(handle) != "ConsoleWindowClass"
            and _title_matches(_window_title(handle), title)
        ):
            found.append(handle)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def _find_child(parent: int, title: str) -> int:
    if os.name != "nt" or not parent:
        return 0
    user32 = _user32()
    found: list[int] = []

    @_enum_proc()
    def callback(hwnd, _lparam):
        handle = _as_hwnd(hwnd)
        if handle and _title_matches(_window_title(handle), title):
            found.append(handle)
            return False
        return True

    user32.EnumChildWindows(parent, callback, 0)
    return found[0] if found else 0


def _hwnd_for(serial: str, parent_hwnd: int = 0) -> int:
    if os.name != "nt" or not serial:
        return 0
    user32 = _user32()
    cached = _as_hwnd(_EMBEDDED.get(serial))
    if cached and user32.IsWindow(cached):
        return cached
    title = window_title(serial)
    hwnd = _find_top_level(title)
    if hwnd:
        return hwnd
    parent = _as_hwnd(parent_hwnd)
    if parent:
        hwnd = _find_child(parent, title)
        if hwnd:
            return hwnd
    process = _PROCS.get(serial)
    if process is not None and process.poll() is None:
        return _find_by_pid(process.pid, title)
    return 0


def _reparent(serial: str, hwnd: int, parent: int, width: int, height: int) -> bool:
    user32 = _user32()
    if not user32.IsWindow(hwnd) or not user32.IsWindow(parent):
        return False
    get_long, set_long = _style_funcs(user32)
    if _as_hwnd(user32.GetParent(hwnd)) != parent:
        user32.SetParent(hwnd, parent)
        set_long(hwnd, _GWL_STYLE, child_window_style(get_long(hwnd, _GWL_STYLE)))
        set_long(hwnd, _GWL_EXSTYLE, child_window_exstyle(get_long(hwnd, _GWL_EXSTYLE)))
        set_long(parent, _GWL_STYLE, int(get_long(parent, _GWL_STYLE)) | _WS_CLIPCHILDREN)
    client_w, client_h = _client_size(parent)
    fit_w = max(1, client_w or int(width))
    fit_h = max(1, client_h or int(height))
    flags = _SWP_FRAMECHANGED | _SWP_SHOWWINDOW | _SWP_NOZORDER | _SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, 0, 0, 0, fit_w, fit_h, flags)
    user32.MoveWindow(hwnd, 0, 0, fit_w, fit_h, True)
    user32.ShowWindow(hwnd, _SW_SHOW)
    if _as_hwnd(user32.GetParent(hwnd)) != parent:
        return False
    _EMBEDDED[serial] = hwnd
    return True


def _find_hwnd(title: str) -> Any:
    hwnd = _find_top_level(title)
    return hwnd or None


def _client_size(hwnd) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    _user32().GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _client_to_screen(hwnd, x: int, y: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT(x, y)
    _user32().ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def _foreground(hwnd) -> None:
    user32 = _user32()
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
    hwnd = _hwnd_for(serial)
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
    hwnd = _hwnd_for(serial)
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
        _user32().SetCursorPos(px, py)
        time.sleep(duration_ms / steps / 1000)
    _release()
    return True
