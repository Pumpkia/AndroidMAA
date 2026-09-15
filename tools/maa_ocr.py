"""Run MaaFramework OCR (GitHub MaaXYZ models) on a local screenshot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Any, Iterable

import numpy as np

from app_paths import APP_PATHS


@dataclass(frozen=True)
class OcrHit:
    text: str
    score: float
    box: tuple[int, int, int, int]


_LOCK = threading.Lock()
_SESSION: Any = None
_DUMMY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _as_box(value: Any) -> tuple[int, int, int, int]:
    if value is None:
        return (0, 0, 0, 0)
    items = list(value)
    if len(items) < 4:
        return (0, 0, 0, 0)
    return (int(items[0]), int(items[1]), int(items[2]), int(items[3]))


def hits_from_detail(detail: Any) -> list[OcrHit]:
    hits: list[OcrHit] = []
    seen: set[tuple[str, tuple[int, int, int, int]]] = set()
    rows: Iterable[Any] = []
    if detail is None:
        return hits
    for source in (
        getattr(detail, "all_results", None),
        getattr(detail, "filtered_results", None),
        [getattr(detail, "best_result", None)],
    ):
        if source:
            rows = list(source)
            break
    for item in rows:
        if item is None:
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        box = _as_box(getattr(item, "box", None))
        key = (text, box)
        if key in seen:
            continue
        seen.add(key)
        score = getattr(item, "score", 0.0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        hits.append(OcrHit(text=text, score=score, box=box))
    return hits


def joined_text(hits: list[OcrHit]) -> str:
    return "".join(item.text for item in hits)


def _ensure_session(resource_dir: Path, data_dir: Path, option: dict | None):
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    from maa.controller import DbgController
    from maa.pipeline import JOCR, JRecognitionType
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    if option is None:
        option_path = APP_PATHS.assets_dir / "config" / "maa_option.json"
        if option_path.is_file():
            try:
                option = json.loads(option_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                option = None
    Toolkit.init_option(data_dir, option)
    dummy = Path(data_dir) / "ocr-dbg"
    dummy.mkdir(parents=True, exist_ok=True)
    placeholder = dummy / "blank.png"
    if not placeholder.is_file():
        placeholder.write_bytes(_DUMMY_PNG)
    resource = Resource()
    resource.set_cpu()
    loaded = resource.post_bundle(resource_dir).wait()
    if not loaded.succeeded:
        raise RuntimeError("Maa OCR 资源加载失败，请确认 resource/model/ocr 存在")
    controller = DbgController(dummy)
    connected = controller.post_connection().wait()
    if not connected.succeeded:
        raise RuntimeError("Maa OCR 调试控制器连接失败")
    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        raise RuntimeError("Maa Tasker 初始化失败")
    _SESSION = {
        "resource": resource,
        "controller": controller,
        "tasker": tasker,
        "JOCR": JOCR,
        "JRecognitionType": JRecognitionType,
    }
    return _SESSION


def recognize_text(
    image,
    roi: list[int] | tuple[int, int, int, int] | None = None,
    *,
    resource_dir: Path | None = None,
    data_dir: Path | None = None,
    option: dict | None = None,
    threshold: float = 0.3,
) -> list[OcrHit]:
    if image is None:
        raise ValueError("请先截图")
    array = np.asarray(image)
    if array.ndim < 2 or array.size == 0:
        raise ValueError("截图无效")
    roi_tuple = (0, 0, 0, 0)
    if roi and len(roi) >= 4 and int(roi[2]) > 0 and int(roi[3]) > 0:
        roi_tuple = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
    with _LOCK:
        session = _ensure_session(
            Path(resource_dir or (APP_PATHS.assets_dir / "resource")),
            Path(data_dir or APP_PATHS.data_dir),
            option,
        )
        param = session["JOCR"](
            expected=[],
            roi=roi_tuple,
            threshold=float(threshold),
            only_rec=False,
        )
        job = session["tasker"].post_recognition(
            session["JRecognitionType"].OCR,
            param,
            array,
        )
        job.wait()
        if not job.succeeded:
            raise RuntimeError("Maa OCR 识别失败")
        detail = job.get()
    recognition = None
    if detail is not None and hasattr(detail, "all_results"):
        recognition = detail
    elif detail is not None:
        nodes = getattr(detail, "nodes", None) or []
        if nodes:
            recognition = getattr(nodes[0], "recognition", None)
        else:
            recognition = getattr(detail, "recognition", None)
    hits = hits_from_detail(recognition)
    if hits:
        return hits
    raise RuntimeError("未识别到文字")
