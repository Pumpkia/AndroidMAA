"""Build a macOS app bundle for the active Qt workbench."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import subprocess
import sys


APP_NAME = "QQJobEditor"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def copytree_fresh(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def chmod_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def platform_tag() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else machine
    return f"macos-{arch}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v2.1.0")
    parser.add_argument(
        "--platform-tools",
        type=Path,
        help="Path to a macOS Android platform-tools directory containing adb.",
    )
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-dmg", action="store_true")
    return parser.parse_args()


def selected_platform_tools(path: Path | None) -> Path:
    source = path or PROJECT_ROOT / "platform-tools"
    adb = source / ("adb.exe" if os.name == "nt" else "adb")
    if not adb.exists():
        raise FileNotFoundError(
            f"Cannot find macOS adb in {source}. Pass --platform-tools with a darwin platform-tools directory."
        )
    return source


def copy_runtime_data(app_dir: Path, platform_tools: Path) -> None:
    copytree_fresh(PROJECT_ROOT / "assets", app_dir / "assets")
    copytree_fresh(PROJECT_ROOT / "jobs", app_dir / "jobs")
    copytree_fresh(platform_tools, app_dir / "platform-tools")
    shutil.copy2(PROJECT_ROOT / "README.md", app_dir / "README.md")
    adb = app_dir / "platform-tools" / "adb"
    if adb.exists():
        chmod_executable(adb)

    debug_path = app_dir / "assets" / "debug"
    if debug_path.exists():
        shutil.rmtree(debug_path)

    agent_binary = app_dir / "_internal" / "MaaAgentBinary" / "maatouch" / "universal" / "maatouch"
    if not agent_binary.exists():
        raise FileNotFoundError(f"Packaged MaaAgentBinary is incomplete: {agent_binary}")


def write_app_bundle(bundle_path: Path, packaged_dir: Path, version: str) -> None:
    if bundle_path.exists():
        shutil.rmtree(bundle_path)

    macos_dir = bundle_path / "Contents" / "MacOS"
    resources_dir = bundle_path / "Contents" / "Resources"
    app_resource_dir = resources_dir / APP_NAME
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    shutil.copytree(packaged_dir, app_resource_dir)

    launcher = macos_dir / APP_NAME
    launcher.write_text(
        "#!/bin/sh\n"
        f'APP_DIR="$(cd "$(dirname "$0")/../Resources/{APP_NAME}" && pwd)"\n'
        f'exec "$APP_DIR/{APP_NAME}" "$@"\n',
        encoding="utf-8",
    )
    chmod_executable(launcher)

    plist = {
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIdentifier": "com.pumpkia.androidmaa.qqjobeditor",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version.removeprefix("v"),
        "CFBundleVersion": version.removeprefix("v"),
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }
    with (bundle_path / "Contents" / "Info.plist").open("wb") as file:
        plistlib.dump(plist, file)


def sign_app_bundle(bundle_path: Path) -> None:
    if shutil.which("codesign") is None:
        return
    run(["codesign", "--force", "--deep", "--sign", "-", str(bundle_path)])


def main() -> None:
    args = parse_args()
    staging_root = PROJECT_ROOT / ".packaging-macos"
    work_path = staging_root / "work"
    staging_dist_path = staging_root / "dist"
    pyinstaller_config_path = staging_root / "pyinstaller-config"
    canonical_dist_path = PROJECT_ROOT / "dist"
    canonical_app_path = canonical_dist_path / f"{APP_NAME}.app"
    release_path = PROJECT_ROOT / "release"
    archive_base = release_path / f"{APP_NAME}-{args.version}-{platform_tag()}"

    platform_tools = selected_platform_tools(args.platform_tools)

    if staging_root.exists():
        shutil.rmtree(staging_root)
    work_path.mkdir(parents=True)
    staging_dist_path.mkdir(parents=True)
    pyinstaller_config_path.mkdir(parents=True)
    release_path.mkdir(parents=True, exist_ok=True)

    if not args.skip_tests:
        run([sys.executable, "tools/validate_schema.py"])
        test_env = os.environ.copy()
        test_env.setdefault("QT_QPA_PLATFORM", "offscreen")
        run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"], env=test_env)

    pyinstaller_env = os.environ.copy()
    pyinstaller_env["PYINSTALLER_CONFIG_DIR"] = str(pyinstaller_config_path)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(work_path),
            "--distpath",
            str(staging_dist_path),
            "QQJobEditor.macos.spec",
        ],
        env=pyinstaller_env,
    )

    packaged_dir = staging_dist_path / APP_NAME
    if not (packaged_dir / APP_NAME).exists():
        raise FileNotFoundError(f"PyInstaller output is incomplete: {packaged_dir}")
    copy_runtime_data(packaged_dir, platform_tools)

    bundle_path = staging_root / f"{APP_NAME}.app"
    write_app_bundle(bundle_path, packaged_dir, args.version)
    sign_app_bundle(bundle_path)

    if canonical_app_path.exists():
        shutil.rmtree(canonical_app_path)
    canonical_dist_path.mkdir(exist_ok=True)
    shutil.copytree(bundle_path, canonical_app_path)

    archive = shutil.make_archive(str(archive_base), "zip", root_dir=staging_root, base_dir=f"{APP_NAME}.app")
    print(f"Release archive: {archive}")
    print(f"Application: {canonical_app_path}")
    if not args.skip_dmg and shutil.which("hdiutil"):
        dmg_path = archive_base.with_suffix(".dmg")
        run(
            [
                "hdiutil",
                "create",
                "-volname",
                APP_NAME,
                "-srcfolder",
                str(bundle_path),
                "-ov",
                "-format",
                "UDZO",
                str(dmg_path),
            ]
        )
        print(f"Disk image: {dmg_path}")


if __name__ == "__main__":
    main()
