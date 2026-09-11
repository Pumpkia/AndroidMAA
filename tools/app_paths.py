"""Resolve Qdd runtime paths and migrate legacy user data safely."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
import uuid


APP_NAME = "Qdd"
DATA_DIR_ENV = "QDD_DATA_DIR"
LAYOUT_VERSION = 1
LAYOUT_MARKER_NAME = ".layout-v1.json"


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path
    assets_dir: Path
    data_dir: Path
    jobs_dir: Path
    user_resource_dir: Path
    template_dir: Path
    game_asset_dir: Path
    logs_dir: Path
    exports_dir: Path
    portable: bool


@dataclass(frozen=True)
class LayoutInitializationResult:
    created_directories: tuple[Path, ...]
    migrated_files: tuple[Path, ...]
    skipped_files: tuple[Path, ...]
    marker_path: Path
    marker_written: bool
    already_initialized: bool


def _normalized_path(path: str | os.PathLike[str]) -> Path:
    expanded = os.path.expanduser(os.fspath(path))
    return Path(os.path.abspath(expanded))


def _default_app_dir(frozen: bool) -> Path:
    if frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_app_paths(
    app_dir: str | os.PathLike[str] | None = None,
    frozen: bool | None = None,
    os_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home_dir: str | os.PathLike[str] | None = None,
) -> AppPaths:
    """Resolve bundled assets and writable user-data paths for this process."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    platform_name = os.name if os_name is None else os_name
    environment = os.environ if environ is None else environ
    application_dir = _normalized_path(app_dir or _default_app_dir(is_frozen))
    assets_dir = application_dir / "assets"

    override = environment.get(DATA_DIR_ENV, "").strip()
    if override:
        data_dir = _normalized_path(override)
        portable = False
        user_resource_dir = data_dir / "resource"
        exports_dir = data_dir / "exports"
    elif platform_name == "nt" and is_frozen:
        if (application_dir / "portable.flag").is_file():
            data_dir = application_dir
            portable = True
            user_resource_dir = assets_dir / "resource"
            exports_dir = application_dir / "exports"
        else:
            local_app_data = environment.get("LOCALAPPDATA", "").strip()
            if local_app_data:
                local_root = _normalized_path(local_app_data)
            else:
                home = _normalized_path(home_dir or Path.home())
                local_root = home / "AppData" / "Local"
            data_dir = local_root / APP_NAME
            portable = False
            user_resource_dir = data_dir / "resource"
            exports_dir = data_dir / "exports"
    else:
        data_dir = application_dir
        portable = True
        user_resource_dir = assets_dir / "resource"
        exports_dir = (
            application_dir / "exports"
            if not is_frozen
            else user_resource_dir / "pipeline"
        )

    return AppPaths(
        app_dir=application_dir,
        assets_dir=assets_dir,
        data_dir=data_dir,
        jobs_dir=data_dir / "jobs",
        user_resource_dir=user_resource_dir,
        template_dir=user_resource_dir / "image" / "jobs",
        game_asset_dir=user_resource_dir / "image" / "assets",
        logs_dir=data_dir / "logs",
        exports_dir=exports_dir,
        portable=portable,
    )


APP_PATHS = resolve_app_paths()


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True

    path_check = getattr(path, "is_junction", None)
    if callable(path_check):
        try:
            if path_check():
                return True
        except OSError:
            return True

    os_check = getattr(os.path, "isjunction", None)
    if callable(os_check):
        try:
            return bool(os_check(path))
        except OSError:
            return True
    return False




def _assert_safe_data_target(data_dir: Path, target: Path) -> None:
    data_root = _normalized_path(data_dir)
    candidate = _normalized_path(target)
    try:
        relative = candidate.relative_to(data_root)
    except ValueError as error:
        raise ValueError(f"Data target escapes data directory: {candidate}") from error

    component = data_root
    for part in (None, *relative.parts):
        if part is not None:
            component /= part
        if _is_link_or_junction(component):
            raise RuntimeError(
                f"Data target contains a symbolic link or junction: {component}"
            )


def _remove_file_if_present(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()


def _ensure_directories(paths: AppPaths) -> tuple[Path, ...]:
    created: list[Path] = []
    seen: set[Path] = set()
    for directory in (
        paths.data_dir,
        paths.jobs_dir,
        paths.template_dir,
        paths.game_asset_dir,
        paths.logs_dir,
        paths.exports_dir,
    ):
        if directory in seen:
            continue
        seen.add(directory)
        _assert_safe_data_target(paths.data_dir, directory)
        if directory.exists():
            if not directory.is_dir():
                raise NotADirectoryError(directory)
            continue
        directory.mkdir(parents=True, exist_ok=False)
        _assert_safe_data_target(paths.data_dir, directory)
        created.append(directory)
    return tuple(created)


def _atomic_copy_no_overwrite(
    source: Path,
    destination: Path,
    data_dir: Path,
) -> bool:
    _assert_safe_data_target(data_dir, destination.parent)
    if _path_exists(destination):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_data_target(data_dir, destination.parent)
    temporary = destination.parent / (
        f".{destination.name}.migrate-{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(source, temporary, follow_symlinks=False)
        _assert_safe_data_target(data_dir, destination.parent)
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            return False
        return True
    finally:
        _remove_file_if_present(temporary)


def _raise_walk_error(error: OSError) -> None:
    raise error


def _migrate_tree(
    source_root: Path,
    destination_root: Path,
    data_dir: Path,
    migrated: list[Path],
    skipped: list[Path],
) -> None:
    if _is_link_or_junction(source_root):
        skipped.append(source_root)
        return
    if not source_root.exists():
        return
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)

    _assert_safe_data_target(data_dir, destination_root)
    source_resolved = _normalized_path(source_root)
    destination_resolved = _normalized_path(destination_root)
    if source_resolved == destination_resolved:
        return
    try:
        destination_resolved.relative_to(source_resolved)
    except ValueError:
        pass
    else:
        raise ValueError(
            f"Migration destination cannot be inside its source: {destination_root}"
        )

    for current_root, directory_names, file_names in os.walk(
        source_root,
        followlinks=False,
        onerror=_raise_walk_error,
    ):
        current = Path(current_root)
        safe_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = current / name
            if _is_link_or_junction(candidate):
                skipped.append(candidate)
            else:
                safe_directories.append(name)
        directory_names[:] = safe_directories

        relative_root = current.relative_to(source_root)
        for name in sorted(file_names):
            source_file = current / name
            if _is_link_or_junction(source_file) or not source_file.is_file():
                skipped.append(source_file)
                continue
            destination_file = destination_root / relative_root / name
            if _atomic_copy_no_overwrite(
                source_file, destination_file, data_dir
            ):
                migrated.append(destination_file)
            else:
                skipped.append(destination_file)


def _valid_layout_marker(marker_path: Path) -> bool:
    if _is_link_or_junction(marker_path) or not marker_path.is_file():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("version") == LAYOUT_VERSION


def _relative_marker_path(path: Path, data_dir: Path) -> str:
    try:
        return path.relative_to(data_dir).as_posix()
    except ValueError:
        return str(path)


def _write_layout_marker(
    marker_path: Path,
    paths: AppPaths,
    migrated_files: list[Path],
) -> None:
    payload = {
        "version": LAYOUT_VERSION,
        "app_dir": str(paths.app_dir),
        "data_dir": str(paths.data_dir),
        "migrated_files": [
            _relative_marker_path(path, paths.data_dir) for path in migrated_files
        ],
    }
    _assert_safe_data_target(paths.data_dir, marker_path.parent)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_data_target(paths.data_dir, marker_path.parent)
    temporary = marker_path.parent / (
        f".{marker_path.name}.write-{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        _assert_safe_data_target(paths.data_dir, marker_path.parent)
        os.replace(temporary, marker_path)
    finally:
        _remove_file_if_present(temporary)


def initialize_data_layout(
    paths: AppPaths = APP_PATHS,
) -> LayoutInitializationResult:
    """Create writable directories and perform the one-time installed migration."""

    created_directories = _ensure_directories(paths)
    marker_path = paths.data_dir / LAYOUT_MARKER_NAME
    if paths.portable:
        return LayoutInitializationResult(
            created_directories=created_directories,
            migrated_files=(),
            skipped_files=(),
            marker_path=marker_path,
            marker_written=False,
            already_initialized=False,
        )
    if _valid_layout_marker(marker_path):
        return LayoutInitializationResult(
            created_directories=created_directories,
            migrated_files=(),
            skipped_files=(),
            marker_path=marker_path,
            marker_written=False,
            already_initialized=True,
        )

    migrated: list[Path] = []
    skipped: list[Path] = []
    _migrate_tree(
        paths.app_dir / "jobs",
        paths.jobs_dir,
        paths.data_dir,
        migrated,
        skipped,
    )
    _migrate_tree(
        paths.app_dir / "assets" / "resource" / "image" / "jobs",
        paths.template_dir,
        paths.data_dir,
        migrated,
        skipped,
    )
    _write_layout_marker(marker_path, paths, migrated)
    return LayoutInitializationResult(
        created_directories=created_directories,
        migrated_files=tuple(migrated),
        skipped_files=tuple(skipped),
        marker_path=marker_path,
        marker_written=True,
        already_initialized=False,
    )
