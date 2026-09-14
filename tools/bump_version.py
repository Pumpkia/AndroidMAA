#!/usr/bin/env python3
"""NnMaa 版本号单一入口。

版本号有两个真正的消费方，必须保持一致：

  1. assets/interface.json              运行时 UI 显示的版本
  2. assets/windows_version_info.txt    PyInstaller 写入 exe 的 Windows 资源
     注意：这一个文件里版本号出现 4 次
     （filevers 元组、prodvers 元组、FileVersion、ProductVersion），
     手工改最容易漏的就是那两个元组。

不需要手工改的地方（构建时自动注入，此处仅作说明）：
  - installer/NnMaa.iss          第 1 行是 #ifndef AppVersion，属于兜底默认值
  - tools/build_release.ps1      第 2 行的 -Version 默认值，命令行传参即覆盖
  二者由 build_release.ps1 用 /DAppVersion= 与 /DOutputBaseFilename= 在打包时注入。

用法：
    python tools/bump_version.py 2.2.0     升到指定版本
    python tools/bump_version.py --sync    以 interface.json 为准，同步 exe 元数据
    python tools/bump_version.py --check   只检查一致性，不一致退出码 1
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERFACE_PATH = ROOT / "assets" / "interface.json"
VERSION_INFO_PATH = ROOT / "assets" / "windows_version_info.txt"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# "interface_version" 的值是整数，不会被这个模式命中，因此无需额外排除
INTERFACE_VERSION_RE = re.compile(r'("version"\s*:\s*")[^"]*(")')


def read_interface_version():
    data = json.loads(INTERFACE_PATH.read_text(encoding="utf-8"))
    return data.get("version")


def read_metadata_version():
    text = VERSION_INFO_PATH.read_text(encoding="utf-8")
    match = re.search(r"StringStruct\('FileVersion', '([^']+)'\)", text)
    return match.group(1) if match else None


def write_interface_version(new):
    text = INTERFACE_PATH.read_text(encoding="utf-8")
    updated = INTERFACE_VERSION_RE.sub(
        lambda m: f"{m.group(1)}{new}{m.group(2)}", text, count=1
    )
    if updated == text:
        return False
    INTERFACE_PATH.write_text(updated, encoding="utf-8")
    return True


def write_metadata_version(old, new):
    text = VERSION_INFO_PATH.read_text(encoding="utf-8")
    updated = text
    if old and old != new:
        old_major, old_minor, old_patch = old.split(".")
        new_major, new_minor, new_patch = new.split(".")
        replacements = (
            (
                f"filevers=({old_major}, {old_minor}, {old_patch}, 0)",
                f"filevers=({new_major}, {new_minor}, {new_patch}, 0)",
            ),
            (
                f"prodvers=({old_major}, {old_minor}, {old_patch}, 0)",
                f"prodvers=({new_major}, {new_minor}, {new_patch}, 0)",
            ),
            (
                f"StringStruct('FileVersion', '{old}')",
                f"StringStruct('FileVersion', '{new}')",
            ),
            (
                f"StringStruct('ProductVersion', '{old}')",
                f"StringStruct('ProductVersion', '{new}')",
            ),
        )
        for target, replacement in replacements:
            updated = updated.replace(target, replacement)
    if updated == text:
        return False
    VERSION_INFO_PATH.write_text(updated, encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="同步 NnMaa 版本号到所有消费方")
    parser.add_argument("version", nargs="?", help="目标版本，如 2.2.0（可带 v 前缀）")
    parser.add_argument(
        "--sync", action="store_true", help="以 interface.json 为准同步 exe 元数据"
    )
    parser.add_argument(
        "--check", action="store_true", help="只检查一致性，不一致时退出码为 1"
    )
    args = parser.parse_args()

    interface_version = read_interface_version()
    metadata_version = read_metadata_version()

    if args.check:
        if interface_version == metadata_version:
            print(f"版本一致：{interface_version}")
            return 0
        print("版本不一致：")
        print(f"  assets/interface.json            {interface_version}")
        print(f"  assets/windows_version_info.txt  {metadata_version}")
        print("修复：python tools/bump_version.py --sync")
        return 1

    if args.sync:
        target = interface_version
    elif args.version:
        target = args.version.lstrip("vV")
    else:
        parser.error("需要指定版本号，或使用 --sync / --check")

    if not target or not SEMVER_RE.match(target):
        parser.error(f"版本号必须是 MAJOR.MINOR.PATCH，收到：{target!r}")

    changed = []
    if interface_version != target and write_interface_version(target):
        changed.append(f"assets/interface.json            -> {target}")
    if metadata_version != target and write_metadata_version(metadata_version, target):
        changed.append(f"assets/windows_version_info.txt  -> {target}")

    if not changed:
        print(f"版本号已是 {target}，无需修改")
        return 0

    print("已更新：")
    for item in changed:
        print("  " + item)
    print()
    print("注意：README.md 含历史版本记录，不做自动替换，请手工确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
