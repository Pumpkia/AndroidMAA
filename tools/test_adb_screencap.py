"""
ADB 截图自测脚本

用途：
    连接第一台 ADB 设备，调用 MaaFramework 截图，并保存到 logs/adb_screencap.png。

运行：
    python tools/test_adb_screencap.py
"""

from pathlib import Path
import sys

import cv2
from maa.controller import AdbController
from maa.toolkit import Toolkit


PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_DIR / "logs" / "adb_screencap.png"


def main():
    Toolkit.init_option(PROJECT_DIR / "assets")

    devices = Toolkit.find_adb_devices()
    if not devices:
        print("未找到 ADB 设备。请确认 USB 调试已开启，并且 adb devices 显示 device。")
        return 1

    device = devices[0]
    print(f"使用设备: {device.name} ({device.address})")

    controller = AdbController(
        adb_path=device.adb_path,
        address=device.address,
        screencap_methods=device.screencap_methods,
        input_methods=device.input_methods,
        config=device.config,
    )

    connect_job = controller.post_connection()
    connect_job.wait()
    if not connect_job.succeeded:
        print("ADB 控制器连接失败。")
        return 1

    screencap_job = controller.post_screencap()
    image = screencap_job.wait().get()
    if image is None:
        print("截图失败：没有拿到图像。")
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(OUTPUT_PATH), image):
        print(f"截图保存失败: {OUTPUT_PATH}")
        return 1

    print(f"截图成功: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

