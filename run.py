"""
QQ 自动登录 - 运行脚本

使用方法:
    python run.py

前提条件:
    1. 已安装 MaaFw: pip install MaaFw
    2. 已连接 Android 设备并开启 USB 调试
    3. assets/resource/image/ 下已放置模板截图
    4. pipeline/login.json 中已填入正确的 QQ 号和密码
"""

import sys
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from maa.toolkit import Toolkit
from maa.resource import Resource
from maa.controller import AdbController
from maa.tasker import Tasker
from maa.define import LoggingLevel


def main():
    # 初始化 MaaFramework
    Toolkit.init_option(Path(__file__).parent / "assets")

    # 加载资源
    resource = Resource()
    resource.set_logging_level(LoggingLevel.Warn)

    assets_dir = Path(__file__).parent / "assets"
    print(f"加载资源: {assets_dir}")
    ret = resource.load(str(assets_dir))
    if not ret:
        print("资源加载失败！请检查 assets 目录结构。")
        return

    # 连接外部安卓设备（ADB 控制器）
    adb_devices = Toolkit.find_adb_devices()
    if not adb_devices:
        print("未找到 ADB 设备！请确认设备已连接并开启 USB 调试。")
        print("提示：先运行 adb devices，确认设备状态为 device。")
        return

    device = adb_devices[0]
    print(f"连接 ADB 设备: {device.name} ({device.address})")
    controller = AdbController(
        adb_path=device.adb_path,
        address=device.address,
        screencap_methods=device.screencap_methods,
        input_methods=device.input_methods,
        config=device.config,
    )

    controller.post_connection().wait()
    print("成功连接 ADB 设备！")

    # 创建 Tasker 并绑定资源
    tasker = Tasker()
    ret = tasker.bind(resource, controller)
    if not ret:
        print("绑定资源失败！")
        return

    # 执行登录任务
    print("开始执行 QQ 登录流程...")
    task_id = tasker.post_task("QQLogin")

    # 等待任务完成
    tasker.wait(task_id)

    print("QQ 登录流程结束！")
    print("请检查 QQ 是否已成功登录。")


if __name__ == "__main__":
    main()

