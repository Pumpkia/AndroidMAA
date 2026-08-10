"""Named UI regions and semantic navigation for Android devices."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time
from typing import Callable
import uuid
import xml.etree.ElementTree as ElementTree

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from job_model import (
    JobDocument, JobStep, ratio_to_rect as model_ratio_to_rect, safe_name,
)


MAP_FORMAT_VERSION = 1
DEVICE_MAP_PATH = "/sdcard/maaqq-semantic-map.xml"
BOUND_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
COMMAND_PREFIXES = (
    "\u5e2e\u6211", "\u8bf7", "\u76f4\u63a5", "\u5bfc\u822a\u5230", "\u524d\u5f80", "\u8fdb\u5165", "\u6253\u5f00", "\u70b9\u51fb", "\u70b9\u5f00",
    "\u9009\u62e9", "\u70b9\u4e00\u4e0b", "\u68c0\u67e5", "\u6821\u9a8c", "\u786e\u8ba4", "\u8bc6\u522b", "\u68c0\u6d4b", "\u5224\u65ad",
)
REGION_PURPOSES = {"click", "check", "recognize"}
PURPOSE_LABELS = {
    "click": "\u70b9\u51fb",
    "check": "\u68c0\u67e5",
    "recognize": "\u8bc6\u522b",
}


def normalize_phrase(value: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).casefold()
    changed = True
    while changed:
        changed = False
        for prefix in COMMAND_PREFIXES:
            compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", prefix).casefold()
            if normalized.startswith(compact) and len(normalized) > len(compact):
                normalized = normalized[len(compact):]
                changed = True
                break
    return normalized

def command_purpose(value: str) -> str:
    compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).casefold()
    polite_prefixes = ("\u5e2e\u6211", "\u8bf7", "\u76f4\u63a5")
    changed = True
    while changed:
        changed = False
        for prefix in polite_prefixes:
            if compact.startswith(prefix) and len(compact) > len(prefix):
                compact = compact[len(prefix):]
                changed = True
                break
    for purpose, prefixes in (
        ("check", ("\u68c0\u67e5", "\u6821\u9a8c", "\u786e\u8ba4")),
        ("recognize", ("\u8bc6\u522b", "\u68c0\u6d4b", "\u5224\u65ad")),
        ("click", ("\u70b9\u51fb", "\u70b9\u5f00", "\u9009\u62e9", "\u70b9\u4e00\u4e0b", "\u6253\u5f00")),
    ):
        if any(compact.startswith(prefix) for prefix in prefixes):
            return purpose
    return ""


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = BOUND_PATTERN.fullmatch(value or "")
    if not match:
        return None
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


@dataclass(frozen=True)
class UiNode:
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]
    clickable: bool = False
    action_bounds: tuple[int, int, int, int] | None = None

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2

    @property
    def click_bounds(self) -> tuple[int, int, int, int]:
        return self.action_bounds or self.bounds

    @property
    def action_center(self) -> tuple[int, int]:
        left, top, right, bottom = self.click_bounds
        return (left + right) // 2, (top + bottom) // 2

    @property
    def label(self) -> str:
        if self.text:
            return self.text
        if self.content_desc:
            return self.content_desc
        if self.resource_id:
            return self.resource_id.rsplit("/", 1)[-1]
        return self.class_name.rsplit(".", 1)[-1]

    @property
    def source(self) -> str:
        if self.text:
            return "\u6587\u5b57"
        if self.content_desc:
            return "\u65e0\u969c\u788d\u63cf\u8ff0"
        if self.resource_id:
            return "\u8d44\u6e90 ID"
        return "\u53ef\u70b9\u51fb\u533a\u57df"


@dataclass
class UiSnapshot:
    width: int
    height: int
    nodes: list[UiNode]


def parse_ui_snapshot(payload: bytes | str) -> UiSnapshot:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    start = payload.find(b"<?xml")
    if start < 0:
        raise ValueError("\u8bbe\u5907\u6ca1\u6709\u8fd4\u56de\u53ef\u89e3\u6790\u7684\u754c\u9762\u7ed3\u6784")
    root = ElementTree.fromstring(payload[start:])
    nodes: list[UiNode] = []
    seen: set[tuple] = set()
    width = 0
    height = 0

    def visit(
        element: ElementTree.Element,
        inherited_action_bounds: tuple[int, int, int, int] | None = None,
    ) -> None:
        nonlocal width, height
        bounds = parse_bounds(element.attrib.get("bounds", ""))
        enabled = element.attrib.get("enabled", "true") != "false"
        clickable = element.attrib.get("clickable", "false") == "true"
        action_bounds = inherited_action_bounds
        if bounds:
            _left, _top, right, bottom = bounds
            width = max(width, right)
            height = max(height, bottom)
            if enabled and clickable:
                action_bounds = bounds
            text = element.attrib.get("text", "").strip()
            content_desc = element.attrib.get("content-desc", "").strip()
            resource_id = element.attrib.get("resource-id", "").strip()
            class_name = element.attrib.get("class", "").strip()
            if enabled and (text or content_desc or resource_id or clickable):
                resolved_action_bounds = action_bounds or bounds
                key = (
                    text, content_desc, resource_id, class_name, bounds,
                    resolved_action_bounds,
                )
                if key not in seen:
                    seen.add(key)
                    nodes.append(UiNode(
                        text=text,
                        content_desc=content_desc,
                        resource_id=resource_id,
                        class_name=class_name,
                        bounds=bounds,
                        clickable=clickable,
                        action_bounds=resolved_action_bounds,
                    ))
        for child in element:
            visit(child, action_bounds)

    visit(root)
    if not width or not height:
        raise ValueError("\u8bbe\u5907\u754c\u9762\u7ed3\u6784\u4e2d\u6ca1\u6709\u6709\u6548\u533a\u57df")
    nodes.sort(key=lambda node: (node.bounds[1], node.bounds[0], node.bounds[3]))
    return UiSnapshot(width, height, nodes)
def scan_device(adb) -> UiSnapshot:
    if not adb.serial:
        raise RuntimeError("请先选择已连接的 ADB 设备")
    adb.shell(["uiautomator", "dump", DEVICE_MAP_PATH])
    return parse_ui_snapshot(adb.shell(["cat", DEVICE_MAP_PATH]))


def validate_bounds_ratio(value: list[float] | tuple[float, ...] | None) -> list[float]:
    if not value:
        return []
    if len(value) != 4:
        raise ValueError("\u533a\u57df\u5750\u6807\u5fc5\u987b\u5305\u542b 4 \u4e2a\u6bd4\u4f8b\u503c")
    ratio = [float(item) for item in value]
    left, top, right, bottom = ratio
    if not all(0 <= item <= 1 for item in ratio):
        raise ValueError("\u533a\u57df\u5750\u6807\u6bd4\u4f8b\u5fc5\u987b\u5728 0 \u5230 1 \u4e4b\u95f4")
    if left >= right or top >= bottom:
        raise ValueError("\u533a\u57df\u5750\u6807\u5fc5\u987b\u5177\u6709\u6709\u6548\u5bbd\u9ad8")
    return [round(item, 6) for item in ratio]


@dataclass
class NamedRegion:
    id: str
    page: str
    name: str
    aliases: list[str] = field(default_factory=list)
    action: str = "click"
    destination: str = ""
    resource_id: str = ""
    text: str = ""
    content_desc: str = ""
    class_name: str = ""
    bounds_ratio: list[float] = field(default_factory=list)
    action_bounds_ratio: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.action == "anchor":
            self.action = "recognize"
        if self.action not in REGION_PURPOSES:
            raise ValueError(f"\u4e0d\u652f\u6301\u7684\u533a\u57df\u7528\u9014: {self.action}")
        self.bounds_ratio = validate_bounds_ratio(self.bounds_ratio)
        self.action_bounds_ratio = validate_bounds_ratio(
            self.action_bounds_ratio or self.bounds_ratio
        )
        if self.action != "click":
            self.destination = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "page": self.page,
            "name": self.name,
            "aliases": self.aliases,
            "action": self.action,
            "destination": self.destination,
            "selector": {
                "resource_id": self.resource_id,
                "text": self.text,
                "content_desc": self.content_desc,
                "class_name": self.class_name,
            },
            "bounds_ratio": self.bounds_ratio,
            "action_bounds_ratio": self.action_bounds_ratio,
        }

    @classmethod
    def from_payload(cls, data: dict) -> "NamedRegion":
        selector = data.get("selector", {})
        if not isinstance(selector, dict):
            selector = {}
        action = data.get("action", "click")
        if action == "anchor":
            action = "recognize"
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            page=data.get("page", ""),
            name=data.get("name", ""),
            aliases=list(data.get("aliases", [])),
            action=action,
            destination=data.get("destination", ""),
            resource_id=selector.get("resource_id", ""),
            text=selector.get("text", ""),
            content_desc=selector.get("content_desc", ""),
            class_name=selector.get("class_name", ""),
            bounds_ratio=data.get("bounds_ratio", []),
            action_bounds_ratio=data.get(
                "action_bounds_ratio",
                data.get("bounds_ratio", []),
            ),
        )

    @property
    def actionable(self) -> bool:
        return self.action == "click"

    @property
    def commandable(self) -> bool:
        return self.action in REGION_PURPOSES

    @property
    def page_marker(self) -> bool:
        return self.action == "recognize"
def node_match_score(region: NamedRegion, node: UiNode) -> int:
    score = 0
    identity_match = False
    for expected, actual, weight in (
        (region.resource_id, node.resource_id, 120),
        (region.content_desc, node.content_desc, 90),
        (region.text, node.text, 80),
    ):
        if expected and expected == actual:
            score += weight
            identity_match = True
    if not identity_match:
        return -1
    if region.class_name and region.class_name == node.class_name:
        score += 10
    if node.clickable:
        score += 2
    return score


def find_region_node(region: NamedRegion, snapshot: UiSnapshot) -> UiNode | None:
    ranked = [(node_match_score(region, node), node) for node in snapshot.nodes]
    ranked = [item for item in ranked if item[0] >= 0]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    top_score = ranked[0][0]
    candidates = [node for score, node in ranked if score == top_score]
    if len(candidates) == 1 or len(region.bounds_ratio) != 4:
        return candidates[0]
    expected_x = (region.bounds_ratio[0] + region.bounds_ratio[2]) * snapshot.width / 2
    expected_y = (region.bounds_ratio[1] + region.bounds_ratio[3]) * snapshot.height / 2
    return min(
        candidates,
        key=lambda node: (node.center[0] - expected_x) ** 2 + (node.center[1] - expected_y) ** 2,
    )


class SemanticMap:
    def __init__(self, regions: list[NamedRegion] | None = None):
        self.regions = regions or []

    @classmethod
    def load(cls, path: Path) -> "SemanticMap":
        if not path.is_file():
            return cls()
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if payload.get("format_version") != MAP_FORMAT_VERSION:
            raise ValueError("不支持的语义地图版本")
        return cls([NamedRegion.from_payload(item) for item in payload.get("regions", [])])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": MAP_FORMAT_VERSION,
            "regions": [region.to_dict() for region in self.regions],
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)

    @property
    def pages(self) -> list[str]:
        values = {region.page for region in self.regions if region.page}
        values.update(region.destination for region in self.regions if region.destination)
        return sorted(values)

    def get(self, region_id: str) -> NamedRegion | None:
        return next((region for region in self.regions if region.id == region_id), None)

    def upsert(self, region: NamedRegion) -> None:
        for index, current in enumerate(self.regions):
            if current.id == region.id:
                self.regions[index] = region
                return
        self.regions.append(region)

    def delete(self, region_id: str) -> None:
        self.regions = [region for region in self.regions if region.id != region_id]

    def resolve_command(self, command: str, page_hint: str = "") -> NamedRegion:
        query = normalize_phrase(command)
        normalized_page_hint = normalize_phrase(page_hint)
        requested_purpose = command_purpose(command)
        if not query:
            raise ValueError("请输入需要点击的区域名称")
        ranked: list[tuple[int, NamedRegion]] = []
        for region in self.regions:
            if not region.commandable or (
                requested_purpose and region.action != requested_purpose
            ):
                continue
            for phrase in (region.name, *region.aliases):
                alias = normalize_phrase(phrase)
                if not alias:
                    continue
                if query == alias:
                    score = 10000 + len(alias)
                elif alias in query:
                    score = 1000 + len(alias)
                elif len(query) >= 2 and query in alias:
                    score = 100 + len(query)
                else:
                    continue
                page = normalize_phrase(region.page)
                if page and page in query:
                    score += 5000 + len(page)
                elif normalized_page_hint and page == normalized_page_hint:
                    score += 2000
                ranked.append((score, region))
        if not ranked:
            raise ValueError(f"没有找到与“{command.strip()}”匹配的命名区域")
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score = ranked[0][0]
        best = {region.id: region for score, region in ranked if score == best_score}
        if len(best) > 1:
            names = "、".join(sorted({region.name for region in best.values()}))
            raise ValueError(f"命令同时匹配多个区域：{names}，请补充页面名")
        return next(iter(best.values()))

    def detect_page(self, snapshot: UiSnapshot) -> str:
        scores: dict[str, tuple[int, int]] = {}
        for page in self.pages:
            page_regions = [region for region in self.regions if region.page == page]
            markers = [region for region in page_regions if region.page_marker]
            evidence = markers or page_regions
            matches = []
            for region in evidence:
                node = find_region_node(region, snapshot)
                if node is not None:
                    matches.append(node_match_score(region, node))
            if matches:
                scores[page] = (len(matches), sum(matches))
        if not scores:
            return ""
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return ""
        return ranked[0][0]
    def plan_route(self, current_page: str, target_page: str) -> list[NamedRegion]:
        if not current_page or not target_page:
            raise ValueError("无法确定当前页面或目标页面")
        if current_page == target_page:
            return []
        queue = deque([(current_page, [])])
        visited = {current_page}
        while queue:
            page, route = queue.popleft()
            for region in self.regions:
                if region.page != page or not region.actionable or not region.destination:
                    continue
                candidate = [*route, region]
                if region.destination == target_page:
                    return candidate
                if region.destination not in visited:
                    visited.add(region.destination)
                    queue.append((region.destination, candidate))
        raise ValueError(f"没有从“{current_page}”到“{target_page}”的已知路径")

    def command_regions(self, command: str, current_page: str = "") -> list[NamedRegion]:
        target = self.resolve_command(command, current_page)
        if not current_page or current_page == target.page:
            return [target]
        return [*self.plan_route(current_page, target.page), target]


def selector_from_node(node: UiNode) -> dict[str, str]:
    return {
        "resource_id": node.resource_id,
        "text": node.text,
        "content_desc": node.content_desc,
        "class_name": node.class_name,
    }


def ratio_from_bounds(
    value: tuple[int, int, int, int],
    snapshot: UiSnapshot,
) -> list[float]:
    left, top, right, bottom = value
    return validate_bounds_ratio([
        left / snapshot.width,
        top / snapshot.height,
        right / snapshot.width,
        bottom / snapshot.height,
    ])


def bounds_ratio(node: UiNode, snapshot: UiSnapshot) -> list[float]:
    return ratio_from_bounds(node.bounds, snapshot)


def node_action_bounds_ratio(node: UiNode, snapshot: UiSnapshot) -> list[float]:
    return ratio_from_bounds(node.click_bounds, snapshot)


def ratio_to_rect(ratio: list[float], device_size: list[int]) -> list[int]:
    return model_ratio_to_rect(validate_bounds_ratio(ratio), device_size)


def region_point(region: NamedRegion, snapshot: UiSnapshot) -> tuple[int, int]:
    node = find_region_node(region, snapshot)
    if node is None:
        raise ValueError(
            f"\u5f53\u524d\u754c\u9762\u672a\u8bc6\u522b\u5230\u201c{region.name}\u201d\uff0c\u5df2\u505c\u6b62\u540e\u7eed\u64cd\u4f5c"
        )
    return node.action_center


def region_to_job_step(region: NamedRegion, device_size: list[int]) -> JobStep:
    if not region.text.strip():
        raise ValueError(
            f"\u533a\u57df\u201c{region.name}\u201d\u6ca1\u6709\u53ef\u7528\u4e8e OCR \u7684\u53ef\u89c1\u6587\u5b57\uff0c"
            "\u8bf7\u9009\u62e9\u6587\u5b57\u5019\u9009\u9879\u540e\u518d\u751f\u6210\u7528\u4f8b"
        )
    if len(region.bounds_ratio) != 4:
        raise ValueError(f"\u533a\u57df\u201c{region.name}\u201d\u6ca1\u6709\u53ef\u7528\u7684\u6587\u5b57\u5750\u6807")
    roi = ratio_to_rect(region.bounds_ratio, device_size)
    if region.action == "click":
        if len(region.action_bounds_ratio) != 4:
            raise ValueError(f"\u533a\u57df\u201c{region.name}\u201d\u6ca1\u6709\u53ef\u7528\u7684\u70b9\u51fb\u533a\u57df")
        action = "Click"
        target = ratio_to_rect(region.action_bounds_ratio, device_size)
        post_delay = 700
    else:
        action = "DoNothing"
        target = None
        post_delay = 200
    return JobStep(
        name=region.name,
        recognition="OCR",
        action=action,
        expected=region.text.strip(),
        roi=roi,
        target=target,
        post_delay=post_delay,
        semantic_purpose=region.action,
        roi_ratio=list(region.bounds_ratio),
        target_ratio=list(region.action_bounds_ratio) if region.action == "click" else None,
    )

@dataclass
class ExecutionResult:
    target: str
    start_page: str
    final_page: str
    clicks: list[str]
    events: list[str] = field(default_factory=list)


class SemanticExecutor:
    def __init__(
        self,
        adb,
        semantic_map: SemanticMap,
        emit: Callable[[str], None],
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.adb = adb
        self.semantic_map = semantic_map
        self.emit = emit
        self.sleep = sleep_fn

    def require_node(
        self,
        region: NamedRegion,
        snapshot: UiSnapshot,
        purpose: str,
    ) -> UiNode:
        node = find_region_node(region, snapshot)
        if node is None:
            raise RuntimeError(
                f"{purpose}\u5931\u8d25\uff1a\u5f53\u524d\u754c\u9762\u672a\u8bc6\u522b\u5230\u201c{region.name}\u201d\uff0c"
                "\u5df2\u505c\u6b62\u540e\u7eed\u64cd\u4f5c"
            )
        return node

    def click(self, region: NamedRegion, snapshot: UiSnapshot) -> None:
        if not region.actionable:
            raise ValueError(f"\u201c{region.name}\u201d\u4e0d\u662f\u70b9\u51fb\u7528\u9014")
        node = self.require_node(region, snapshot, "\u70b9\u51fb\u524d\u8bc6\u522b")
        x, y = node.action_center
        self.emit(f"\u70b9\u51fb\uff1a{region.page} / {region.name} ({x}, {y})")
        self.adb.shell(["input", "tap", str(x), str(y)])

    def verify(self, region: NamedRegion, snapshot: UiSnapshot) -> None:
        label = PURPOSE_LABELS[region.action]
        node = self.require_node(region, snapshot, label)
        left, top, right, bottom = node.bounds
        self.emit(
            f"{label}\u6210\u529f\uff1a{region.page} / {region.name} "
            f"({left}, {top}, {right}, {bottom})"
        )

    def execute(self, command: str, page_hint: str = "") -> ExecutionResult:
        snapshot = scan_device(self.adb)
        detected = self.semantic_map.detect_page(snapshot)
        current_page = detected or page_hint.strip()
        target = self.semantic_map.resolve_command(command, current_page)
        if detected:
            self.emit(f"\u5f53\u524d\u9875\u9762\uff1a{detected}")
        elif current_page:
            self.emit(f"\u4f7f\u7528\u9875\u9762\u63d0\u793a\uff1a{current_page}")

        clicks: list[str] = []
        events: list[str] = []
        target_node = find_region_node(target, snapshot)
        if target_node is None and current_page != target.page:
            if not current_page:
                raise RuntimeError(
                    "\u65e0\u6cd5\u8bc6\u522b\u5f53\u524d\u9875\u9762\uff0c\u4e0d\u4f1a\u6267\u884c\u540e\u7eed\u70b9\u51fb"
                )
            route = self.semantic_map.plan_route(current_page, target.page)
            for edge in route:
                self.click(edge, snapshot)
                clicks.append(edge.name)
                events.append(f"\u70b9\u51fb {edge.name}")
                self.sleep(0.9)
                snapshot = scan_device(self.adb)
                observed = self.semantic_map.detect_page(snapshot)
                if not observed:
                    raise RuntimeError(
                        f"\u70b9\u51fb\u201c{edge.name}\u201d\u540e\u672a\u8bc6\u522b\u5230\u76ee\u6807\u9875\u9762\uff0c"
                        "\u5df2\u505c\u6b62\u540e\u7eed\u64cd\u4f5c"
                    )
                current_page = observed
                if observed != edge.destination:
                    raise RuntimeError(
                        f"\u70b9\u51fb\u201c{edge.name}\u201d\u540e\u5230\u8fbe\u4e86\u201c{observed}\u201d\uff0c"
                        f"\u9884\u671f\u4e3a\u201c{edge.destination}\u201d"
                    )

        if target.action == "click":
            self.click(target, snapshot)
            clicks.append(target.name)
            events.append(f"\u70b9\u51fb {target.name}")
        else:
            self.verify(target, snapshot)
            events.append(f"{PURPOSE_LABELS[target.action]} {target.name}")

        final_page = target.destination or target.page
        if target.action == "click" and target.destination:
            self.sleep(0.7)
            observed = self.semantic_map.detect_page(scan_device(self.adb))
            if not observed:
                raise RuntimeError(
                    f"\u70b9\u51fb\u201c{target.name}\u201d\u540e\u672a\u8bc6\u522b\u5230\u76ee\u6807\u9875\u9762\uff0c"
                    "\u5df2\u505c\u6b62\u540e\u7eed\u64cd\u4f5c"
                )
            if observed != target.destination:
                raise RuntimeError(
                    f"\u70b9\u51fb\u201c{target.name}\u201d\u540e\u5230\u8fbe\u4e86\u201c{observed}\u201d\uff0c"
                    f"\u9884\u671f\u4e3a\u201c{target.destination}\u201d"
                )
            final_page = observed
        return ExecutionResult(
            target.name,
            detected or page_hint.strip(),
            final_page,
            clicks,
            events,
        )
class RegionPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("semanticPreview")
        self.setAccessibleName("候选区域预览")
        self.setAccessibleDescription("蓝色虚线显示文字坐标，橙色框显示实际点击区域")
        self.setMinimumHeight(180)
        self.setMaximumHeight(230)
        self._pixmap = QPixmap()
        self._node: UiNode | None = None

    def set_image(self, image) -> None:
        if image is None or getattr(image, "size", 0) == 0:
            self._pixmap = QPixmap()
        else:
            height, width = image.shape[:2]
            qimage = QImage(
                image.data,
                width,
                height,
                image.strides[0],
                QImage.Format.Format_BGR888,
            ).copy()
            self._pixmap = QPixmap.fromImage(qimage)
        self.update()

    def set_node(self, node: UiNode | None) -> None:
        self._node = node
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F2F2F7"))
        if self._pixmap.isNull():
            painter.setPen(QColor("#8E8E93"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "\u6682\u65e0\u9884\u89c8")
            return
        area = self.rect().adjusted(8, 8, -8, -8)
        fitted = self._pixmap.scaled(
            area.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRect(
            area.center().x() - fitted.width() // 2,
            area.center().y() - fitted.height() // 2,
            fitted.width(),
            fitted.height(),
        )
        painter.drawPixmap(target, fitted)
        if self._node is None:
            return

        scale_x = target.width() / self._pixmap.width()
        scale_y = target.height() / self._pixmap.height()

        def mapped(bounds: tuple[int, int, int, int]) -> QRect:
            left, top, right, bottom = bounds
            return QRect(
                round(target.left() + left * scale_x),
                round(target.top() + top * scale_y),
                max(1, round((right - left) * scale_x)),
                max(1, round((bottom - top) * scale_y)),
            )

        action_rect = mapped(self._node.click_bounds)
        action_pen = QPen(QColor("#FF9500"), 3)
        painter.setPen(action_pen)
        painter.setBrush(QColor(255, 149, 0, 35))
        painter.drawRect(action_rect)
        center = action_rect.center()
        painter.drawLine(center.x() - 7, center.y(), center.x() + 7, center.y())
        painter.drawLine(center.x(), center.y() - 7, center.x(), center.y() + 7)

        text_pen = QPen(QColor("#0066CC"), 2, Qt.PenStyle.DashLine)
        painter.setPen(text_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(mapped(self._node.bounds))

class SemanticNavigatorPage(QWidget):
    log_signal = Signal(str)

    def __init__(self, app, map_path: Path):
        super().__init__()
        self.app = app
        self.map_path = map_path
        self.snapshot: UiSnapshot | None = None
        self.screen_image = None
        self.snapshot_serial = ""
        self.nodes: list[UiNode] = []
        self.generated_steps: list[JobStep] = []
        self.generated_size = [720, 1600]
        self.editing_id = ""
        self.load_error = ""
        try:
            self.semantic_map = SemanticMap.load(map_path)
        except Exception as error:
            self.semantic_map = SemanticMap()
            self.load_error = str(error)
        self.log_signal.connect(self.append_log)
        self.build_ui()
        self.refresh_regions()
        if self.load_error:
            self.append_log(f"语义地图加载失败：{self.load_error}")

    def build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        header.setObjectName("metadataBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 10, 18, 10)
        title = QLabel("语义导航")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self.state = QLabel("就绪")
        self.state.setObjectName("statusPill")
        self.state.setProperty("runState", "idle")
        header_layout.addWidget(self.state)
        self.scan_button = QPushButton("扫描当前界面")
        self.scan_button.setObjectName("primaryButton")
        self.scan_button.clicked.connect(self.scan)
        header_layout.addWidget(self.scan_button)
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_scan_pane())
        splitter.addWidget(self.build_map_pane())
        splitter.addWidget(self.build_command_pane())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([560, 470, 470])
        root.addWidget(splitter, 1)

    def pane(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("semanticPane")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        return frame, layout

    def build_scan_pane(self) -> QFrame:
        pane, layout = self.pane("\u5f53\u524d\u754c\u9762\u533a\u57df")
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("\u9875\u9762\u540d\u79f0"))
        self.page_name = QComboBox()
        self.page_name.setEditable(True)
        self.page_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        page_row.addWidget(self.page_name, 1)
        layout.addLayout(page_row)

        self.scan_table = QTableWidget(0, 5)
        self.scan_table.setAccessibleName("当前界面候选区域")
        self.scan_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scan_table.setHorizontalHeaderLabels([
            "\u5019\u9009\u540d\u79f0", "\u6765\u6e90", "\u63a7\u4ef6",
            "\u6587\u5b57\u5750\u6807", "\u533a\u57df\u5750\u6807",
        ])
        self.scan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.scan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.scan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.scan_table.verticalHeader().setVisible(False)
        header = self.scan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.scan_table.setColumnWidth(1, 54)
        self.scan_table.setColumnWidth(2, 72)
        self.scan_table.setColumnWidth(3, 108)
        self.scan_table.setColumnWidth(4, 108)
        self.scan_table.itemSelectionChanged.connect(self.node_selected)
        layout.addWidget(self.scan_table, 1)

        self.region_preview = RegionPreview()
        layout.addWidget(self.region_preview)
        self.test_tap_button = QPushButton("\u8bd5\u70b9\u9009\u4e2d\u533a\u57df")
        self.test_tap_button.setToolTip("\u5728\u5f53\u524d\u8bbe\u5907\u4e0a\u70b9\u51fb\u533a\u57df\u4e2d\u5fc3")
        self.test_tap_button.setEnabled(False)
        self.test_tap_button.clicked.connect(self.preview_selected_node)
        layout.addWidget(self.test_tap_button)
        return pane
    def build_map_pane(self) -> QFrame:
        pane, layout = self.pane("命名与页面关系")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.region_name = QLineEdit()
        self.aliases = QLineEdit()
        self.region_type = QComboBox()
        self.region_type.addItem("\u70b9\u51fb", "click")
        self.region_type.addItem("\u68c0\u67e5", "check")
        self.region_type.addItem("\u8bc6\u522b", "recognize")
        self.region_type.currentIndexChanged.connect(self.update_purpose_controls)
        self.destination = QComboBox()
        self.destination.setEditable(True)
        self.destination.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("区域名称", self.region_name)
        form.addRow("别名", self.aliases)
        form.addRow("用途", self.region_type)
        self.destination_label = QLabel("\u70b9\u51fb\u540e\u9875\u9762")
        form.addRow(self.destination_label, self.destination)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存命名")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save_region)
        buttons.addWidget(self.save_button)
        self.reset_button = QPushButton("新建")
        self.reset_button.clicked.connect(self.reset_editor)
        buttons.addWidget(self.reset_button)
        self.delete_button = QPushButton("删除")
        self.delete_button.setProperty("danger", True)
        self.delete_button.clicked.connect(self.delete_region)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.region_tree = QTreeWidget()
        self.region_tree.setHeaderLabels(["页面", "区域", "用途", "到达页面"])
        self.region_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.region_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.region_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.region_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.region_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.region_tree.itemDoubleClicked.connect(lambda item, _column: self.edit_region(item))
        layout.addWidget(self.region_tree, 1)
        self.update_purpose_controls()
        return pane

    def build_command_pane(self) -> QFrame:
        pane, layout = self.pane("语义生成")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.command = QLineEdit()
        self.command.setClearButtonEnabled(True)
        self.command.returnPressed.connect(self.generate_steps)
        self.case_name = QLineEdit("语义用例")
        self.case_category = QLineEdit("语义导航")
        form.addRow("区域命令", self.command)
        form.addRow("用例名称", self.case_name)
        form.addRow("分类", self.case_category)
        layout.addLayout(form)

        generate_row = QHBoxLayout()
        self.generate_button = QPushButton("添加为用例步骤")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generate_steps)
        generate_row.addWidget(self.generate_button)
        self.clear_steps_button = QPushButton("清空步骤")
        self.clear_steps_button.clicked.connect(self.clear_generated_steps)
        generate_row.addWidget(self.clear_steps_button)
        layout.addLayout(generate_row)

        self.generated_table = QTableWidget(0, 4)
        self.generated_table.setHorizontalHeaderLabels([
            "\u5e8f\u53f7", "\u6b65\u9aa4", "\u7528\u9014", "\u5750\u6807 / \u533a\u57df",
        ])
        self.generated_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.generated_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.generated_table.verticalHeader().setVisible(False)
        header = self.generated_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.generated_table, 1)

        save_row = QHBoxLayout()
        self.save_job_button = QPushButton("保存到用例库")
        self.save_job_button.setObjectName("primaryButton")
        self.save_job_button.clicked.connect(self.save_generated_job)
        save_row.addWidget(self.save_job_button)
        self.edit_job_button = QPushButton("转到用例录制")
        self.edit_job_button.clicked.connect(self.edit_generated_job)
        save_row.addWidget(self.edit_job_button)
        layout.addLayout(save_row)

        self.execute_button = QPushButton("在设备上预览")
        self.execute_button.clicked.connect(self.execute_command)
        layout.addWidget(self.execute_button)
        self.log = QPlainTextEdit()
        self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        layout.addWidget(self.log)
        return pane

    def update_purpose_controls(self) -> None:
        is_click = self.region_type.currentData() == "click"
        self.destination.setEnabled(is_click)
        self.destination_label.setEnabled(is_click)
        if not is_click:
            self.destination.setCurrentText("")

    def set_state(self, text: str, state: str) -> None:
        self.state.setText(text)
        self.state.setProperty("runState", state)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def set_busy(self, busy: bool) -> None:
        for control in (
            self.scan_button, self.scan_table, self.page_name, self.region_name,
            self.aliases, self.region_type, self.destination, self.save_button,
            self.reset_button, self.delete_button, self.region_tree, self.command,
            self.case_name, self.case_category, self.generate_button,
            self.clear_steps_button, self.generated_table, self.save_job_button,
            self.edit_job_button, self.execute_button, self.test_tap_button,
        ):
            control.setEnabled(not busy)
        if not busy:
            self.update_purpose_controls()
            self.test_tap_button.setEnabled(
                self.selected_node() is not None and bool(self.app.adb.serial)
            )

    def append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {message}")

    def scan(self) -> None:
        if not self.app.adb.serial:
            QMessageBox.warning(self, "ADB \u8bbe\u5907", "\u8bf7\u5148\u9009\u62e9\u5df2\u8fde\u63a5\u7684 ADB \u8bbe\u5907\u3002")
            return
        serial = self.app.adb.serial
        session = self.app.adb.for_serial(serial)
        self.set_busy(True)
        self.set_state("\u626b\u63cf\u4e2d", "running")
        self.app.set_execution_active(True, "semantic_scan")

        def operation():
            try:
                snapshot = scan_device(session)
                image = session.screenshot()
                return True, (snapshot, image)
            except Exception as error:
                return False, str(error)

        def done(result):
            self.app.set_execution_active(False)
            self.set_busy(False)
            if self.app.adb.serial != serial:
                self.set_state("\u8bbe\u5907\u5df2\u5207\u6362", "failed")
                self.append_log("\u626b\u63cf\u671f\u95f4\u8bbe\u5907\u5df2\u5207\u6362\uff0c\u5df2\u4e22\u5f03\u65e7\u626b\u63cf\u7ed3\u679c")
                self.app.finish_close_if_requested()
                return
            ok, value = result
            if not ok:
                self.set_state("\u5931\u8d25", "failed")
                QMessageBox.critical(self, "\u626b\u63cf\u5931\u8d25", value)
                self.app.finish_close_if_requested()
                return
            snapshot, image = value
            self.snapshot = snapshot
            self.snapshot_serial = serial
            self.screen_image = image
            self.nodes = snapshot.nodes
            self.region_preview.set_image(image)
            self.region_preview.set_node(None)
            self.populate_nodes()
            detected = self.semantic_map.detect_page(snapshot)
            if detected:
                self.page_name.setCurrentText(detected)
            self.set_state(f"\u53d1\u73b0 {len(self.nodes)} \u4e2a\u533a\u57df", "success")
            self.append_log(
                f"\u5df2\u626b\u63cf {snapshot.width} \u00d7 {snapshot.height} \u754c\u9762\uff0c"
                f"\u5171 {len(self.nodes)} \u4e2a\u5019\u9009\u533a\u57df"
            )
            self.app.finish_close_if_requested()

        self.app.run_async(operation, done)
    def populate_nodes(self) -> None:
        self.scan_table.clearSelection()
        self.scan_table.setRowCount(len(self.nodes))
        for row, node in enumerate(self.nodes):
            def display(bounds: tuple[int, int, int, int]) -> str:
                left, top, right, bottom = bounds
                return f"{left},{top},{right - left},{bottom - top}"

            values = (
                node.label,
                node.source,
                node.class_name.rsplit(".", 1)[-1],
                display(node.bounds),
                display(node.click_bounds),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.scan_table.setItem(row, column, item)
        self.test_tap_button.setEnabled(False)

    def node_selected(self) -> None:
        node = self.selected_node()
        self.region_preview.set_node(node)
        self.test_tap_button.setEnabled(
            node is not None and bool(self.app.adb.serial)
        )
        if node is not None and not self.editing_id:
            self.region_name.setText(node.label)

    def selected_node(self) -> UiNode | None:
        row = self.scan_table.currentRow()
        return self.nodes[row] if 0 <= row < len(self.nodes) else None

    def preview_selected_node(self) -> None:
        node = self.selected_node()
        if node is None:
            QMessageBox.information(self, "\u5019\u9009\u9884\u89c8", "\u8bf7\u5148\u9009\u62e9\u4e00\u6761\u5019\u9009\u533a\u57df\u3002")
            return
        if not self.app.adb.serial:
            QMessageBox.warning(self, "ADB \u8bbe\u5907", "\u8bf7\u5148\u9009\u62e9\u5df2\u8fde\u63a5\u7684 ADB \u8bbe\u5907\u3002")
            return
        serial = self.app.adb.serial
        if self.snapshot_serial != serial:
            QMessageBox.warning(
                self,
                "\u5019\u9009\u9884\u89c8",
                "\u5f53\u524d\u5019\u9009\u4e0d\u5c5e\u4e8e\u5df2\u9009\u8bbe\u5907\uff0c\u8bf7\u91cd\u65b0\u626b\u63cf\u3002",
            )
            return
        session = self.app.adb.for_serial(serial)
        x, y = node.action_center
        self.set_busy(True)
        self.set_state("\u8bd5\u70b9\u4e2d", "running")
        self.app.set_execution_active(True, "semantic_preview")

        def operation():
            try:
                session.shell(["input", "tap", str(x), str(y)])
                return True, ""
            except Exception as error:
                return False, str(error)

        def done(result):
            self.app.set_execution_active(False)
            self.set_busy(False)
            if self.app.adb.serial != serial:
                self.set_state("\u8bbe\u5907\u5df2\u5207\u6362", "failed")
                self.append_log("\u8bd5\u70b9\u671f\u95f4\u8bbe\u5907\u5df2\u5207\u6362\uff0c\u5df2\u4e22\u5f03\u65e7\u7ed3\u679c")
                self.app.finish_close_if_requested()
                return
            ok, error = result
            if not ok:
                self.set_state("\u8bd5\u70b9\u5931\u8d25", "failed")
                QMessageBox.warning(self, "\u8bd5\u70b9\u5931\u8d25", error)
                self.app.finish_close_if_requested()
                return
            self.set_state("\u5df2\u8bd5\u70b9", "success")
            self.append_log(
                f"\u8bd5\u70b9\uff1a{node.label} ({x}, {y})\uff0c\u533a\u57df {node.click_bounds}"
            )
            self.app.toast(f"\u5df2\u8bd5\u70b9\uff1a{node.label}")
            self.app.finish_close_if_requested()

        self.app.run_async(operation, done)
    def save_region(self) -> None:
        page = self.page_name.currentText().strip()
        name = self.region_name.text().strip()
        node = self.selected_node()
        existing = self.semantic_map.get(self.editing_id) if self.editing_id else None
        if not page:
            QMessageBox.warning(self, "页面名称", "请填写当前页面名称。")
            self.page_name.setFocus()
            return
        if not name:
            QMessageBox.warning(self, "区域名称", "请填写区域名称。")
            self.region_name.setFocus()
            return
        if node is None and existing is None:
            QMessageBox.warning(self, "选择区域", "请先从当前界面区域中选择一项。")
            return
        selector = selector_from_node(node) if node else {
            "resource_id": existing.resource_id,
            "text": existing.text,
            "content_desc": existing.content_desc,
            "class_name": existing.class_name,
        }
        text_ratio = (
            bounds_ratio(node, self.snapshot)
            if node and self.snapshot
            else existing.bounds_ratio
        )
        action_ratio = (
            node_action_bounds_ratio(node, self.snapshot)
            if node and self.snapshot
            else existing.action_bounds_ratio
        )
        aliases = [
            value.strip()
            for value in re.split(r"[,，]", self.aliases.text())
            if value.strip()
        ]
        region = NamedRegion(
            id=self.editing_id or uuid.uuid4().hex,
            page=page,
            name=name,
            aliases=aliases,
            action=self.region_type.currentData(),
            destination=self.destination.currentText().strip(),
            bounds_ratio=text_ratio,
            action_bounds_ratio=action_ratio,
            **selector,
        )
        self.semantic_map.upsert(region)
        self.semantic_map.save(self.map_path)
        self.editing_id = region.id
        self.refresh_regions()
        self.set_state("已保存", "success")
        self.append_log(f"已保存：{region.page} / {region.name}")

    def refresh_regions(self) -> None:
        self.region_tree.clear()
        for region in sorted(self.semantic_map.regions, key=lambda item: (item.page, item.name)):
            item = QTreeWidgetItem([
                region.page,
                region.name,
                PURPOSE_LABELS.get(region.action, region.action),
                region.destination,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, region.id)
            self.region_tree.addTopLevelItem(item)
        current_page = self.page_name.currentText() if hasattr(self, "page_name") else ""
        current_destination = self.destination.currentText() if hasattr(self, "destination") else ""
        for combo, current in (
            (self.page_name, current_page),
            (self.destination, current_destination),
        ):
            combo.blockSignals(True)
            combo.clear()
            if combo is self.destination:
                combo.addItem("")
            combo.addItems(self.semantic_map.pages)
            combo.setCurrentText(current)
            combo.blockSignals(False)

    def edit_region(self, item: QTreeWidgetItem) -> None:
        region = self.semantic_map.get(item.data(0, Qt.ItemDataRole.UserRole))
        if region is None:
            return
        self.editing_id = region.id
        self.page_name.setCurrentText(region.page)
        self.region_name.setText(region.name)
        self.aliases.setText("，".join(region.aliases))
        purpose_index = self.region_type.findData(region.action)
        self.region_type.setCurrentIndex(max(0, purpose_index))
        self.update_purpose_controls()
        self.destination.setCurrentText(region.destination)
        self.scan_table.clearSelection()
        self.set_state("编辑中", "idle")

    def reset_editor(self) -> None:
        self.editing_id = ""
        self.region_name.clear()
        self.aliases.clear()
        self.region_type.setCurrentIndex(0)
        self.destination.setCurrentText("")
        self.update_purpose_controls()
        self.scan_table.clearSelection()
        self.region_preview.set_node(None)
        self.set_state("\u5c31\u7eea", "idle")
    def delete_region(self) -> None:
        region_id = self.editing_id
        if not region_id and self.region_tree.currentItem():
            region_id = self.region_tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        region = self.semantic_map.get(region_id)
        if region is None:
            QMessageBox.information(self, "删除命名", "请先选择已保存的命名区域。")
            return
        if QMessageBox.question(
            self, "删除命名", f"确认删除“{region.page} / {region.name}”吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.semantic_map.delete(region.id)
        self.semantic_map.save(self.map_path)
        self.reset_editor()
        self.refresh_regions()
        self.append_log(f"已删除：{region.page} / {region.name}")

    def unique_step_name(self, name: str) -> str:
        existing = {step.name for step in self.generated_steps}
        if name not in existing:
            return name
        suffix = 2
        while f"{name} {suffix}" in existing:
            suffix += 1
        return f"{name} {suffix}"

    def generate_steps(self) -> None:
        command = self.command.text().strip()
        if not command:
            self.command.setFocus()
            return
        if self.snapshot is None:
            QMessageBox.information(self, "生成步骤", "请先扫描当前界面。")
            return
        if not self.semantic_map.regions:
            QMessageBox.information(self, "语义地图", "请先保存至少一个命名区域。")
            return
        page = self.page_name.currentText().strip()
        try:
            regions = self.semantic_map.command_regions(command, page)
            if self.snapshot.width <= self.snapshot.height:
                self.generated_size = [
                    720,
                    round(self.snapshot.height * 720 / self.snapshot.width),
                ]
            else:
                self.generated_size = [
                    round(self.snapshot.width * 720 / self.snapshot.height),
                    720,
                ]
            for region in regions:
                step = region_to_job_step(region, self.generated_size)
                step.name = self.unique_step_name(step.name)
                self.generated_steps.append(step)
            self.refresh_generated_steps()
            self.set_state("步骤已生成", "success")
            self.append_log(f"已生成：{' → '.join(region.name for region in regions)}")
            self.command.clear()
        except Exception as error:
            QMessageBox.warning(self, "生成步骤失败", str(error))

    def refresh_generated_steps(self) -> None:
        self.generated_table.setRowCount(len(self.generated_steps))
        for row, step in enumerate(self.generated_steps):
            purpose = step.semantic_purpose or (
                "click" if step.action == "Click" else "check"
            )
            region = step.target if purpose == "click" else step.roi
            prefix = "\u533a\u57df" if purpose == "click" else "\u6587\u5b57"
            coordinate = (
                f"{prefix} " + ",".join(str(value) for value in region)
                if region
                else "-"
            )
            values = (
                str(row + 1),
                step.name,
                PURPOSE_LABELS.get(purpose, purpose),
                coordinate,
            )
            for column, value in enumerate(values):
                self.generated_table.setItem(row, column, QTableWidgetItem(value))
    def clear_generated_steps(self) -> None:
        self.generated_steps.clear()
        self.refresh_generated_steps()
        self.set_state("步骤已清空", "idle")

    def generated_document(self) -> JobDocument:
        name = self.case_name.text().strip()
        category = self.case_category.text().strip() or "语义导航"
        if not name:
            raise ValueError("请填写用例名称")
        if not self.generated_steps:
            raise ValueError("请先生成至少一个用例步骤")
        document = JobDocument(
            name=name,
            category=category,
            device_size=list(self.generated_size),
            steps=list(self.generated_steps),
        )
        errors = document.validate()
        if errors:
            raise ValueError("\n".join(errors))
        return document

    def save_generated_job(self) -> None:
        try:
            document = self.generated_document()
            output = (
                self.map_path.parent
                / safe_name(document.category, "语义导航")
                / f"{safe_name(document.name, 'semantic_job')}.maa_job.json"
            )
            if output.exists() and QMessageBox.question(
                self, "覆盖用例", f"“{document.name}”已经存在，确认覆盖吗？"
            ) != QMessageBox.StandardButton.Yes:
                return
            document.save(output)
            self.app.playback.refresh_library()
            self.app.toast(f"语义用例已保存：{output.name}")
            self.set_state("已保存到用例库", "success")
            self.append_log(f"用例已保存：{output}")
        except Exception as error:
            QMessageBox.warning(self, "保存用例失败", str(error))

    def edit_generated_job(self) -> None:
        try:
            document = self.generated_document()
            self.app.document = document
            self.app.current_path = None
            self.app.record.case_name.setText(document.name)
            self.app.record.case_category.setText(document.category)
            self.app.record.refresh_steps(0)
            self.app.record.clear_marks()
            self.app.set_dirty(True)
            self.app.switch_page(0)
        except Exception as error:
            QMessageBox.warning(self, "转到用例录制失败", str(error))

    def execute_command(self) -> None:
        command = self.command.text().strip()
        if not command:
            self.command.setFocus()
            return
        if not self.app.adb.serial:
            QMessageBox.warning(self, "ADB 设备", "请先选择已连接的 ADB 设备。")
            return
        if not self.semantic_map.regions:
            QMessageBox.information(self, "语义地图", "请先扫描界面并保存至少一个命名区域。")
            return
        page_hint = self.page_name.currentText().strip()
        serial = self.app.adb.serial
        session = self.app.adb.for_serial(serial)
        self.set_busy(True)
        self.set_state("执行中", "running")
        self.app.set_execution_active(True, "semantic")
        self.append_log(f"命令：{command}")

        def operation():
            try:
                executor = SemanticExecutor(
                    session, self.semantic_map, self.log_signal.emit
                )
                return True, executor.execute(command, page_hint)
            except Exception as error:
                return False, str(error)

        def done(result):
            self.app.set_execution_active(False)
            self.set_busy(False)
            if self.app.adb.serial != serial:
                self.set_state("\u8bbe\u5907\u5df2\u5207\u6362", "failed")
                self.append_log("\u8bed\u4e49\u6267\u884c\u671f\u95f4\u8bbe\u5907\u5df2\u5207\u6362\uff0c\u5df2\u4e22\u5f03\u65e7\u7ed3\u679c")
                self.app.finish_close_if_requested()
                return
            ok, value = result
            if ok:
                self.set_state("已完成", "success")
                self.page_name.setCurrentText(value.final_page)
                self.append_log(f"完成：{' → '.join(value.events)}")
            else:
                self.set_state("失败", "failed")
                self.append_log(f"失败：{value}")
                QMessageBox.warning(self, "命令执行失败", value)
            self.app.finish_close_if_requested()

        self.app.run_async(operation, done)

    def device_changed(self, serial: str) -> None:
        self.snapshot = None
        self.snapshot_serial = ""
        self.screen_image = None
        self.nodes = []
        self.scan_table.setRowCount(0)
        self.region_preview.set_image(None)
        self.region_preview.set_node(None)
        self.test_tap_button.setEnabled(False)
        if serial:
            self.set_state("\u5f85\u626b\u63cf", "idle")
        else:
            self.set_state("\u672a\u8fde\u63a5", "idle")
