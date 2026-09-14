"""Build a macOS app bundle for the active Qt workbench."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import plistlib
import shutil
import stat
import subprocess
import sys


APP_NAME = "NnMaa"
BUNDLE_IDENTIFIER = "com.pumpkia.androidmaa.nnmaa"
ICON_FILE_NAME = "nnmaa.icns"
MACOS_SPEC_NAME = "NnMaa.macos.spec"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def copytree_fresh(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_path(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def copy_file_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for current_root, directory_names, file_names in os.walk(source, followlinks=False):
        current = Path(current_root)
        directory_names[:] = [
            name for name in directory_names if not (current / name).is_symlink()
        ]
        relative = current.relative_to(source)
        target_root = destination / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for name in file_names:
            source_file = current / name
            if source_file.is_symlink() or not source_file.is_file():
                continue
            shutil.copy2(source_file, target_root / name)


def chmod_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def platform_tag(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    arch = {
        "aarch64": "arm64",
        "amd64": "x86_64",
    }.get(machine, machine)
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
    adb = source / "adb"
    if not adb.exists():
        raise FileNotFoundError(
            f"Cannot find macOS adb in {source}. Pass --platform-tools with a darwin platform-tools directory."
        )
    return source


def stage_clean_runtime_data(
    app_dir: Path,
    platform_tools: Path,
    *,
    project_root: Path | None = None,
) -> None:
    root = project_root or PROJECT_ROOT
    copytree_fresh(root / "assets", app_dir / "assets")
    remove_path(app_dir / "jobs")
    (app_dir / "jobs").mkdir(parents=True)
    copytree_fresh(platform_tools, app_dir / "platform-tools")
    shutil.copy2(root / "README.md", app_dir / "README.md")

    recorded_images = app_dir / "assets" / "resource" / "image" / "jobs"
    remove_path(recorded_images)

    adb = app_dir / "platform-tools" / "adb"
    if adb.exists():
        chmod_executable(adb)

    debug_path = app_dir / "assets" / "debug"
    remove_path(debug_path)

    agent_binary = app_dir / "_internal" / "MaaAgentBinary" / "maatouch" / "universal" / "maatouch"
    if not agent_binary.exists():
        raise FileNotFoundError(f"Packaged MaaAgentBinary is incomplete: {agent_binary}")


def bundle_runtime_dir(bundle_path: Path) -> Path:
    return bundle_path / "Contents" / "Resources" / APP_NAME


def validate_icns(icon_path: Path) -> None:
    data = icon_path.read_bytes()
    if (
        len(data) < 8
        or data[:4] != b"icns"
        or int.from_bytes(data[4:8], "big") != len(data)
    ):
        raise ValueError(f"Invalid ICNS file: {icon_path}")


def write_app_bundle(
    bundle_path: Path,
    packaged_dir: Path,
    version: str,
    *,
    icon_path: Path | None = None,
) -> None:
    remove_path(bundle_path)

    macos_dir = bundle_path / "Contents" / "MacOS"
    resources_dir = bundle_path / "Contents" / "Resources"
    app_resource_dir = bundle_runtime_dir(bundle_path)
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    shutil.copytree(packaged_dir, app_resource_dir)

    source_icon = icon_path or PROJECT_ROOT / "assets" / "icons" / ICON_FILE_NAME
    validate_icns(source_icon)
    shutil.copy2(source_icon, resources_dir / ICON_FILE_NAME)

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
        "CFBundleIconFile": ICON_FILE_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
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


def safe_template_relative_path(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or "\x00" in text:
        return None

    windows_path = PureWindowsPath(text)
    normalized = text.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if windows_path.anchor or windows_path.drive or posix_path.is_absolute():
        return None
    if not posix_path.parts or any(part == ".." for part in posix_path.parts):
        return None
    return Path(*posix_path.parts)


def resolved_child(root: Path, relative: Path) -> Path | None:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def iter_job_files(jobs_dir: Path):
    if not jobs_dir.is_dir():
        return
    for current_root, directory_names, file_names in os.walk(jobs_dir, followlinks=False):
        current = Path(current_root)
        directory_names[:] = [
            name for name in directory_names if not (current / name).is_symlink()
        ]
        for name in file_names:
            path = current / name
            if name.endswith(".maa_job.json") and path.is_file() and not path.is_symlink():
                yield path


def copy_referenced_templates(
    jobs_dir: Path,
    source_image_root: Path,
    destination_image_root: Path,
) -> list[Path]:
    if not source_image_root.is_dir():
        return []
    destination_image_root.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    seen: set[Path] = set()

    for job_file in iter_job_files(jobs_dir):
        try:
            payload = json.loads(job_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
            continue

        for step in payload["steps"]:
            if not isinstance(step, dict):
                continue
            relative = safe_template_relative_path(step.get("template"))
            if relative is None or relative in seen:
                continue
            seen.add(relative)

            try:
                source = resolved_child(source_image_root, relative)
                destination = resolved_child(destination_image_root, relative)
            except OSError:
                continue
            if source is None or destination is None or not source.is_file():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(relative)
    return copied


def preserve_local_data(existing_bundle: Path, new_bundle: Path) -> list[Path]:
    existing_runtime = bundle_runtime_dir(existing_bundle)
    new_runtime = bundle_runtime_dir(new_bundle)
    existing_jobs = existing_runtime / "jobs"
    new_jobs = new_runtime / "jobs"
    if not existing_jobs.is_dir():
        return []

    remove_path(new_jobs)
    copy_file_tree(existing_jobs, new_jobs)
    return copy_referenced_templates(
        existing_jobs,
        existing_runtime / "assets" / "resource" / "image",
        new_runtime / "assets" / "resource" / "image",
    )


def verify_blank_runtime_data(bundle_path: Path) -> None:
    runtime = bundle_runtime_dir(bundle_path)
    jobs_dir = runtime / "jobs"
    if not jobs_dir.is_dir() or any(jobs_dir.iterdir()):
        raise RuntimeError(f"Release jobs directory is not blank: {jobs_dir}")
    recorded_images = runtime / "assets" / "resource" / "image" / "jobs"
    if path_exists(recorded_images):
        raise RuntimeError(f"Release contains recorded job images: {recorded_images}")


def artifact_paths(
    release_path: Path,
    version: str,
    target_platform: str,
) -> tuple[Path, Path]:
    base = release_path / f"{APP_NAME}-{version}-{target_platform}"
    return Path(f"{base}.zip"), Path(f"{base}.dmg")


def create_release_artifacts(
    bundle_path: Path,
    release_path: Path,
    version: str,
    target_platform: str,
    *,
    skip_dmg: bool,
) -> tuple[Path, Path | None]:
    release_path.mkdir(parents=True, exist_ok=True)
    archive_path, dmg_path = artifact_paths(release_path, version, target_platform)
    remove_path(archive_path)
    archive = Path(
        shutil.make_archive(
            str(archive_path.with_suffix("")),
            "zip",
            root_dir=bundle_path.parent,
            base_dir=bundle_path.name,
        )
    )

    created_dmg: Path | None = None
    if not skip_dmg and shutil.which("hdiutil"):
        remove_path(dmg_path)
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
        created_dmg = dmg_path
    return archive, created_dmg


def promote_app_bundle(
    bundle_path: Path,
    canonical_app_path: Path,
    backup_app_path: Path,
) -> None:
    launcher = bundle_path / "Contents" / "MacOS" / APP_NAME
    if not launcher.is_file():
        raise FileNotFoundError(f"Candidate application is incomplete: {bundle_path}")
    if path_exists(backup_app_path):
        raise FileExistsError(f"Refusing to overwrite application backup: {backup_app_path}")

    canonical_app_path.parent.mkdir(parents=True, exist_ok=True)
    moved_existing = False
    try:
        if path_exists(canonical_app_path):
            shutil.move(str(canonical_app_path), str(backup_app_path))
            moved_existing = True
        shutil.move(str(bundle_path), str(canonical_app_path))
        promoted_launcher = canonical_app_path / "Contents" / "MacOS" / APP_NAME
        if not promoted_launcher.is_file():
            raise FileNotFoundError(
                f"Canonical application promotion failed: {canonical_app_path}"
            )
    except Exception:
        remove_path(canonical_app_path)
        if moved_existing and path_exists(backup_app_path):
            shutil.move(str(backup_app_path), str(canonical_app_path))
        raise
    remove_path(backup_app_path)


def finalize_release(
    bundle_path: Path,
    canonical_app_path: Path,
    backup_app_path: Path,
    release_path: Path,
    version: str,
    target_platform: str,
    *,
    skip_dmg: bool,
) -> tuple[Path, Path | None]:
    verify_blank_runtime_data(bundle_path)
    sign_app_bundle(bundle_path)
    artifacts = create_release_artifacts(
        bundle_path,
        release_path,
        version,
        target_platform,
        skip_dmg=skip_dmg,
    )
    if path_exists(canonical_app_path):
        preserve_local_data(canonical_app_path, bundle_path)
        sign_app_bundle(bundle_path)
    promote_app_bundle(bundle_path, canonical_app_path, backup_app_path)
    return artifacts


def main() -> None:
    args = parse_args()
    target_platform = platform_tag()
    staging_root = PROJECT_ROOT / ".packaging-macos"
    work_path = staging_root / "work"
    staging_dist_path = staging_root / "dist"
    pyinstaller_config_path = staging_root / "pyinstaller-config"
    canonical_app_path = PROJECT_ROOT / "dist" / f"{APP_NAME}.app"
    backup_app_path = staging_root / "previous-app"
    release_path = PROJECT_ROOT / "release"

    platform_tools = selected_platform_tools(args.platform_tools)

    if path_exists(backup_app_path):
        raise FileExistsError(
            f"Previous application backup requires manual recovery: {backup_app_path}"
        )
    remove_path(staging_root)
    work_path.mkdir(parents=True)
    staging_dist_path.mkdir(parents=True)
    pyinstaller_config_path.mkdir(parents=True)

    try:
        if not args.skip_tests:
            run([sys.executable, "tools/validate_schema.py"])
            test_env = os.environ.copy()
            test_env.setdefault("QT_QPA_PLATFORM", "offscreen")
            run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tools",
                    "-p",
                    "test_*.py",
                ],
                env=test_env,
            )

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
                MACOS_SPEC_NAME,
            ],
            env=pyinstaller_env,
        )

        packaged_dir = staging_dist_path / APP_NAME
        if not (packaged_dir / APP_NAME).exists():
            raise FileNotFoundError(f"PyInstaller output is incomplete: {packaged_dir}")
        stage_clean_runtime_data(packaged_dir, platform_tools)

        bundle_path = staging_root / f"{APP_NAME}.app"
        write_app_bundle(
            bundle_path,
            packaged_dir,
            args.version,
            icon_path=PROJECT_ROOT / "assets" / "icons" / ICON_FILE_NAME,
        )
        archive, dmg_path = finalize_release(
            bundle_path,
            canonical_app_path,
            backup_app_path,
            release_path,
            args.version,
            target_platform,
            skip_dmg=args.skip_dmg,
        )
        print(f"Release archive: {archive}")
        if dmg_path is not None:
            print(f"Disk image: {dmg_path}")
        print(f"Application: {canonical_app_path}")
    finally:
        if path_exists(backup_app_path):
            print(f"Previous application backup kept at: {backup_app_path}")
        else:
            remove_path(staging_root)


if __name__ == "__main__":
    main()
