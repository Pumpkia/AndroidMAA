"""奇迹暖暖衣橱与模板资产目录。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from uuid import uuid4

from job_model import JobDocument, JobStep, safe_name


ASSET_FORMAT_VERSION = 1
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ASSET_CATEGORIES = (
    "发型",
    "连衣裙",
    "外套",
    "上衣",
    "下装",
    "袜子",
    "鞋子",
    "饰品",
    "妆容",
    "翅膀",
    "特效",
    "主界面",
    "关卡",
    "弹窗",
)


def _template_key(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def templates_match(left: str, right: str) -> bool:
    first = _template_key(left)
    second = _template_key(right)
    if not first or not second:
        return False
    if first == second:
        return True
    left_path = Path(first)
    right_path = Path(second)
    if left_path.name != right_path.name:
        return False
    return first.endswith(second) or second.endswith(first)


def read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if data.startswith(b"\x89PNG") and len(data) >= 24:
        import struct

        width, height = struct.unpack(">II", data[16:24])
        if width > 0 and height > 0:
            return int(width), int(height)
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if image is None:
        return None
    return int(image.shape[1]), int(image.shape[0])


def click_step_from_asset(asset: GameAsset) -> JobStep:
    size = read_image_size(asset.path)
    roi = [0, 0, size[0], size[1]] if size else None
    target = [size[0] // 2, size[1] // 2] if size else None
    return JobStep(
        name=asset.name,
        recognition="TemplateMatch",
        action="Click",
        template=asset.relative,
        roi=roi,
        target=target,
    )


@dataclass(frozen=True)
class GameAsset:
    name: str
    category: str
    path: Path
    relative: str
    file_size: int


class AssetLibrary:
    """Manage 奇迹暖暖 template images under resource/image/assets."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_categories(self) -> list[str]:
        names = list(ASSET_CATEGORIES)
        seen = set(names)
        if self.root.is_dir():
            for path in sorted(self.root.iterdir(), key=lambda item: item.name):
                if path.is_dir() and not path.name.startswith(".") and path.name not in seen:
                    names.append(path.name)
                    seen.add(path.name)
        return names

    def list_assets(self, category: str | None = None) -> list[GameAsset]:
        assets: list[GameAsset] = []
        categories = [category] if category else self.list_categories()
        for name in categories:
            folder = self.root / name
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
                asset = self._from_path(path, name)
                if asset is not None:
                    assets.append(asset)
        return assets

    def import_file(self, source: Path, category: str, name: str = "") -> GameAsset:
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        suffix = source.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError("只支持导入 png、jpg、jpeg、webp、bmp 图片")
        folder = self._category_dir(category)
        stem = safe_name(name or source.stem, "asset")
        destination = self._unique_path(folder / f"{stem}{suffix}")
        shutil.copy2(source, destination)
        asset = self._from_path(destination, folder.name)
        if asset is None:
            raise RuntimeError("导入后无法读取资产文件")
        return asset

    def save_image(self, image, category: str, name: str) -> GameAsset:
        import cv2

        folder = self._category_dir(category)
        destination = self._unique_path(folder / f"{safe_name(name, 'asset')}.png")
        succeeded, encoded = cv2.imencode(".png", image)
        if not succeeded:
            raise RuntimeError("截图编码失败")
        encoded.tofile(str(destination))
        asset = self._from_path(destination, folder.name)
        if asset is None:
            raise RuntimeError("保存后无法读取资产文件")
        return asset

    def delete(self, asset: GameAsset) -> None:
        path = Path(asset.path)
        if path.is_file():
            path.unlink()

    def find_references(self, jobs_dir: Path, relative: str) -> list[Path]:
        hits: list[Path] = []
        root = Path(jobs_dir)
        if not root.exists():
            return hits
        for path in root.rglob("*.maa_job.json"):
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            if any(templates_match(step.template, relative) for step in document.steps):
                hits.append(path)
        return hits

    def _category_dir(self, category: str) -> Path:
        name = safe_name(category, "主界面")
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _from_path(self, path: Path, category: str) -> GameAsset | None:
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            return None
        relative = Path("assets") / category / path.name
        return GameAsset(
            name=path.stem,
            category=category,
            path=path.resolve(),
            relative=relative.as_posix(),
            file_size=path.stat().st_size,
        )

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        return path.with_name(f"{path.stem}-{uuid4().hex[:8]}{path.suffix}")
