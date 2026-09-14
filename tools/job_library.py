"""Safe filesystem operations for the Maa job library."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from job_model import JobDocument, safe_name


JOB_FILE_SUFFIX = ".maa_job.json"
_INVALID_CATEGORY_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class CategoryInfo:
    """A logical category and the jobs assigned to it."""

    name: str
    path: Path
    job_count: int


@dataclass(frozen=True)
class CategoryRenameResult:
    path: Path
    jobs_updated: int
    moved_jobs: tuple[tuple[Path, Path], ...] = ()


@dataclass(frozen=True)
class CategoryDeleteResult:
    path: Path
    jobs_deleted: int
    files_deleted: int
    directories_deleted: int
    deleted_jobs: tuple[Path, ...] = ()


class JobLibrary:
    """Manage category folders and job documents below a single trusted root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def list_categories(self) -> list[CategoryInfo]:
        """Return physical and document-defined categories, including empty ones."""
        physical = {
            path.name: path.resolve()
            for path in self.root.iterdir()
            if path.is_dir() and not self._is_link(path)
        }
        counts: dict[str, int] = {name: 0 for name in physical}
        for job_path in self._iter_job_paths():
            relative = job_path.relative_to(self.root)
            if len(relative.parts) > 1 and relative.parts[0] in physical:
                category = relative.parts[0]
            else:
                try:
                    category = JobDocument.load(job_path).category.strip()
                except Exception:
                    category = ""
            if category:
                try:
                    category = self._validate_category_name(category)
                except (TypeError, ValueError):
                    continue
                counts[category] = counts.get(category, 0) + 1

        return [
            CategoryInfo(name, physical.get(name, (self.root / name).resolve(strict=False)), counts[name])
            for name in sorted(counts, key=str.casefold)
        ]

    def create_category(self, name: str) -> Path:
        """Create a category and return its absolute directory path."""
        clean_name = self._validate_category_name(name)
        path = self._category_path(clean_name)
        if path.exists() or self._category_members(clean_name):
            raise FileExistsError(f"分类已存在: {clean_name}")
        path.mkdir()
        return path.resolve()

    def rename_category(self, category: str, new_name: str) -> CategoryRenameResult:
        """Rename a logical category, move its jobs, and repair prerequisite paths."""
        source_name = self._validate_category_name(category)
        clean_name = self._validate_category_name(new_name)
        source = self._require_category(source_name)
        members = self._category_members(source_name)
        if source_name == clean_name:
            return CategoryRenameResult(source.resolve(strict=False), 0)

        destination = self._category_path(clean_name)
        destination_members = self._category_members(clean_name)
        same_directory = source.exists() and destination.exists() and source.samefile(destination)
        if (destination.exists() and not same_directory) or destination_members:
            raise FileExistsError(f"分类已存在: {clean_name}")

        records: list[tuple[Path, Path | None, JobDocument | None]] = []
        for path in members:
            relative = path.relative_to(source) if source.exists() and path.is_relative_to(source) else None
            try:
                document = JobDocument.load(path)
            except Exception:
                document = None
            records.append((path, relative, document))

        final_path = destination
        if source.exists():
            if same_directory:
                temporary = self.root / f".category-rename-{uuid4().hex}"
                source.rename(temporary)
                try:
                    temporary.rename(destination)
                except Exception:
                    temporary.rename(source)
                    raise
            else:
                source.rename(destination)
        else:
            destination.mkdir()

        moved_jobs: list[tuple[Path, Path]] = []
        jobs_updated = 0
        for old_path, relative, document in records:
            if relative is not None:
                new_path = final_path / relative
                if document is not None:
                    document.category = clean_name
                    self._save_document_atomic(document, new_path)
                    jobs_updated += 1
            else:
                if document is None:
                    continue
                base_name = safe_name(
                    old_path.name[: -len(JOB_FILE_SUFFIX)],
                    safe_name(document.name, "job"),
                )
                new_path = final_path / f"{base_name}{JOB_FILE_SUFFIX}"
                if new_path.exists():
                    new_path = self._unique_job_path(final_path, base_name)
                document.category = clean_name
                self._save_document_atomic(document, new_path)
                old_path.unlink()
                jobs_updated += 1
            moved_jobs.append((old_path.resolve(strict=False), new_path.resolve(strict=False)))

        replacements = {
            self._relative_reference(old_path): self._relative_reference(new_path)
            for old_path, new_path in moved_jobs
        }
        self._rewrite_prerequisites(replacements)
        return CategoryRenameResult(final_path.resolve(), jobs_updated, tuple(moved_jobs))

    def delete_category(self, category: str) -> CategoryDeleteResult:
        """Delete a logical category recursively; the caller confirms the operation."""
        clean_name = self._validate_category_name(category)
        path = self._require_category(clean_name)
        members = self._category_members(clean_name)
        deleted_jobs = tuple(item.resolve(strict=False) for item in members)
        deleted_references = {self._relative_reference(item): None for item in members}

        files_deleted = 0
        directories_deleted = 0
        if path.exists():
            directories_deleted = 1
            for item in path.rglob("*"):
                if item.is_dir() and not self._is_link(item):
                    directories_deleted += 1
                else:
                    files_deleted += 1
            shutil.rmtree(path)

        for job_path in members:
            if path.exists() or not job_path.exists():
                continue
            job_path.unlink()
            files_deleted += 1

        if deleted_references:
            self._rewrite_prerequisites(deleted_references)
        return CategoryDeleteResult(
            path=path.resolve(strict=False),
            jobs_deleted=len(deleted_jobs),
            files_deleted=files_deleted,
            directories_deleted=directories_deleted,
            deleted_jobs=deleted_jobs,
        )

    def delete_job(self, job_path: Path) -> Path:
        """Delete one job document and remove it from prerequisite lists."""
        path = self._existing_job_path(job_path)
        reference = self._relative_reference(path)
        path.unlink()
        self._rewrite_prerequisites({reference: None})
        return path

    def move_job(self, job_path: Path, target_category: str) -> Path:
        """Move a job into a category and synchronize dependent references."""
        source = self._existing_job_path(job_path)
        category_name = self._validate_category_name(target_category)
        target_directory = self._require_category(category_name)
        if not target_directory.exists():
            target_directory.mkdir()
        document = JobDocument.load(source)

        source_stem = source.name[: -len(JOB_FILE_SUFFIX)]
        base_name = safe_name(source_stem, safe_name(document.name, "job"))
        destination = target_directory / f"{base_name}{JOB_FILE_SUFFIX}"
        if destination.exists() and not source.samefile(destination):
            destination = self._unique_job_path(target_directory, base_name)

        old_reference = self._relative_reference(source)
        document.category = category_name
        if source == destination.resolve(strict=False):
            self._save_document_atomic(document, source)
            return source

        self._save_document_atomic(document, destination)
        try:
            source.unlink()
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        resolved_destination = destination.resolve()
        self._rewrite_prerequisites(
            {old_reference: self._relative_reference(resolved_destination)}
        )
        return resolved_destination

    def _category_members(self, category: str) -> list[Path]:
        category_path = self._category_path(category)
        members: set[Path] = set()
        if category_path.exists():
            if not category_path.is_dir():
                raise NotADirectoryError(category_path)
            if self._is_link(category_path):
                raise ValueError(f"分类不能是链接目录: {category}")
            for path in category_path.rglob(f"*{JOB_FILE_SUFFIX}"):
                if path.is_file() and not self._is_link(path):
                    members.add(path.resolve())

        for path in self._iter_job_paths():
            if path in members:
                continue
            try:
                if JobDocument.load(path).category.strip() == category:
                    members.add(path)
            except Exception:
                continue
        return sorted(members, key=lambda item: str(item).casefold())

    def _category_path(self, name: str) -> Path:
        clean_name = self._validate_category_name(name)
        path = self.root / clean_name
        resolved = path.resolve(strict=False)
        if resolved.parent != self.root:
            raise ValueError(f"分类路径越界: {name}")
        return path

    def _require_category(self, name: str) -> Path:
        path = self._category_path(name)
        if path.exists():
            if not path.is_dir():
                raise NotADirectoryError(path)
            if self._is_link(path):
                raise ValueError(f"分类不能是链接目录: {name}")
            self._ensure_within_root(path.resolve())
            return path
        if self._category_members(name):
            return path
        raise FileNotFoundError(f"找不到分类: {name}")

    def _existing_job_path(self, job_path: Path) -> Path:
        raw_path = Path(job_path)
        candidate = raw_path if raw_path.is_absolute() else self.root / raw_path
        if self._is_link(candidate):
            raise ValueError(f"作业文件不能是链接: {job_path}")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            raise FileNotFoundError(f"找不到作业: {job_path}") from None
        self._ensure_within_root(resolved)
        if not resolved.is_file():
            raise FileNotFoundError(f"找不到作业: {job_path}")
        if not resolved.name.endswith(JOB_FILE_SUFFIX):
            raise ValueError(f"不是 Maa 作业文件: {job_path}")
        return resolved

    def find_by_name(self, name: str) -> Path | None:
        for path in self._iter_job_paths():
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            if document.name == name:
                return path
        return None

    def _iter_job_paths(self) -> list[Path]:
        return sorted(
            (
                path.resolve()
                for path in self.root.rglob(f"*{JOB_FILE_SUFFIX}")
                if path.is_file() and not self._is_link(path)
            ),
            key=lambda item: str(item).casefold(),
        )

    def _relative_reference(self, path: Path) -> str:
        absolute = Path(path).absolute()
        resolved = absolute.resolve(strict=False)
        self._ensure_within_root(resolved)
        try:
            relative = absolute.relative_to(self.root)
        except ValueError:
            relative = resolved.relative_to(self.root)
        return relative.as_posix()

    def _rewrite_prerequisites(self, replacements: dict[str, str | None]) -> int:
        normalized = {key.replace("\\", "/"): value for key, value in replacements.items()}
        updated = 0
        for job_path in self._iter_job_paths():
            try:
                document = JobDocument.load(job_path)
            except Exception:
                continue
            changed = False
            rewritten: list[str] = []
            for reference in document.prerequisites:
                key = reference.replace("\\", "/")
                replacement = normalized.get(key, reference)
                if replacement is None:
                    changed = True
                    continue
                if replacement != reference:
                    changed = True
                if replacement in rewritten:
                    changed = True
                    continue
                rewritten.append(replacement)
            if changed:
                document.prerequisites = rewritten
                self._save_document_atomic(document, job_path)
                updated += 1
        return updated

    def _ensure_within_root(self, path: Path) -> None:
        if path != self.root and not path.is_relative_to(self.root):
            raise ValueError(f"路径越界: {path}")

    @staticmethod
    def _validate_category_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("分类名称必须是字符串")
        if not name or name != name.strip():
            raise ValueError("分类名称不能为空或包含首尾空格")
        if name in {".", ".."} or _INVALID_CATEGORY_CHARS.search(name):
            raise ValueError(f"非法分类名称: {name}")
        if name.endswith((".", " ")):
            raise ValueError(f"非法分类名称: {name}")
        if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Windows 保留名称不能用作分类: {name}")
        return name

    @staticmethod
    def _is_link(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())

    @staticmethod
    def _save_document_atomic(document: JobDocument, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            document.save(temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _unique_job_path(directory: Path, base_name: str) -> Path:
        suffix = 2
        while True:
            candidate = directory / f"{base_name}_{suffix}{JOB_FILE_SUFFIX}"
            if not candidate.exists():
                return candidate
            suffix += 1
