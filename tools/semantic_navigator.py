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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from job_model import JobDocument, JobStep, safe_name


MAP_FORMAT_VERSION = 1
DEVICE_MAP_PATH = "/sdcard/maaqq-semantic-map.xml"
BOUND_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
COMMAND_PREFIXES = ("帮我", "请", "直接", "导航到", "前往", "进入", "打开", "点击", "点开", "选择", "点一下")


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

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
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
            return "文字"
        if self.content_desc:
            return "无障碍描述"
        if self.resource_id:
            return "资源 ID"
        return "可点击区域"


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
        raise ValueError("设备没有返回可解析的界面结构")
    root = ElementTree.fromstring(payload[start:])
    nodes: list[UiNode] = []
    seen: set[tuple] = set()
    width = 0
    height = 0
    for element in root.iter("node"):
        bounds = parse_bounds(element.attrib.get("bounds", ""))
        if not bounds or element.attrib.get("enabled", "true") == "false":
            continue
        _left, _top, right, bottom = bounds
        width = max(width, right)
        height = max(height, bottom)
        text = element.attrib.get("text", "").strip()
        content_desc = element.attrib.get("content-desc", "").strip()
        resource_id = element.attrib.get("resource-id", "").strip()
        class_name = element.attrib.get("class", "").strip()
        clickable = element.attrib.get("clickable", "false") == "true"
        if not (text or content_desc or resource_id or clickable):
            continue
        key = (text, content_desc, resource_id, class_name, bounds)
        if key in seen:
            continue
        seen.add(key)
        nodes.append(UiNode(text, content_desc, resource_id, class_name, bounds, clickable))
    if not width or not height:
        raise ValueError("设备界面结构中没有有效区域")
    nodes.sort(key=lambda node: (node.bounds[1], node.bounds[0], node.bounds[3]))
    return UiSnapshot(width, height, nodes)


def scan_device(adb) -> UiSnapshot:
    if not adb.serial:
        raise RuntimeError("请先选择已连接的 ADB 设备")
    adb.shell(["uiautomator", "dump", DEVICE_MAP_PATH])
    return parse_ui_snapshot(adb.shell(["cat", DEVICE_MAP_PATH]))


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
        }

    @classmethod
    def from_payload(cls, data: dict) -> "NamedRegion":
        selector = data.get("selector", {})
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            page=data.get("page", ""),
            name=data.get("name", ""),
            aliases=data.get("aliases", []),
            action=data.get("action", "click"),
            destination=data.get("destination", ""),
            resource_id=selector.get("resource_id", ""),
            text=selector.get("text", ""),
            content_desc=selector.get("content_desc", ""),
            class_name=selector.get("class_name", ""),
            bounds_ratio=data.get("bounds_ratio", []),
        )

    @property
    def actionable(self) -> bool:
        return self.action == "click"


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
        if not query:
            raise ValueError("请输入需要点击的区域名称")
        ranked: list[tuple[int, NamedRegion]] = []
        for region in self.regions:
            if not region.actionable:
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
            matches = []
            for region in self.regions:
                if region.page != page:
                    continue
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


def bounds_ratio(node: UiNode, snapshot: UiSnapshot) -> list[float]:
    left, top, right, bottom = node.bounds
    return [
        round(left / snapshot.width, 6),
        round(top / snapshot.height, 6),
        round(right / snapshot.width, 6),
        round(bottom / snapshot.height, 6),
    ]


def region_point(region: NamedRegion, snapshot: UiSnapshot) -> tuple[int, int]:
    node = find_region_node(region, snapshot)
    if node is not None:
        return node.center
    if len(region.bounds_ratio) != 4:
        raise ValueError(f"当前界面找不到区域“{region.name}”")
    left, top, right, bottom = region.bounds_ratio
    return (
        round((left + right) * snapshot.width / 2),
        round((top + bottom) * snapshot.height / 2),
    )


def region_to_job_step(region: NamedRegion, device_size: list[int]) -> JobStep:
    if not region.actionable or len(region.bounds_ratio) != 4:
        raise ValueError(f"区域“{region.name}”没有可生成步骤的点击位置")
    left, top, right, bottom = region.bounds_ratio
    target = [
        round((left + right) * device_size[0] / 2),
        round((top + bottom) * device_size[1] / 2),
    ]
    return JobStep(
        name=region.name,
        recognition="DirectHit",
        action="Click",
        target=target,
        post_delay=700,
    )


@dataclass
class ExecutionResult:
    target: str
    start_page: str
    final_page: str
    clicks: list[str]


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

    def click(self, region: NamedRegion, snapshot: UiSnapshot) -> None:
        if not region.actionable:
            raise ValueError(f"“{region.name}”仅用于页面识别，不能点击")
        x, y = region_point(region, snapshot)
        self.emit(f"点击：{region.page} / {region.name} ({x}, {y})")
        self.adb.shell(["input", "tap", str(x), str(y)])

    def execute(self, command: str, page_hint: str = "") -> ExecutionResult:
        snapshot = scan_device(self.adb)
        detected = self.semantic_map.detect_page(snapshot)
        current_page = detected or page_hint.strip()
        target = self.semantic_map.resolve_command(command, current_page)
        if detected:
            self.emit(f"当前页面：{detected}")
        elif current_page:
            self.emit(f"使用页面提示：{current_page}")

        clicks: list[str] = []
        target_node = find_region_node(target, snapshot)
        if target_node is None or (current_page and current_page != target.page):
            route = self.semantic_map.plan_route(current_page, target.page)
            for edge in route:
                self.click(edge, snapshot)
                clicks.append(edge.name)
                self.sleep(0.9)
                snapshot = scan_device(self.adb)
                current_page = edge.destination
                observed = self.semantic_map.detect_page(snapshot)
                if observed:
                    current_page = observed
                if observed and observed != edge.destination:
                    raise RuntimeError(
                        f"点击“{edge.name}”后到达了“{observed}”，预期为“{edge.destination}”"
                    )

        self.click(target, snapshot)
        clicks.append(target.name)
        final_page = target.destination or target.page
        if target.destination:
            self.sleep(0.7)
            observed = self.semantic_map.detect_page(scan_device(self.adb))
            if observed:
                final_page = observed
        return ExecutionResult(target.name, detected or page_hint.strip(), final_page, clicks)


class SemanticNavigatorPage(QWidget):
    log_signal = Signal(str)

    def __init__(self, app, map_path: Path):
        super().__init__()
        self.app = app
        self.map_path = map_path
        self.snapshot: UiSnapshot | None = None
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
        pane, layout = self.pane("当前界面区域")
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("页面名称"))
        self.page_name = QComboBox()
        self.page_name.setEditable(True)
        self.page_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        page_row.addWidget(self.page_name, 1)
        layout.addLayout(page_row)
        self.scan_table = QTableWidget(0, 4)
        self.scan_table.setHorizontalHeaderLabels(["候选名称", "来源", "控件", "坐标"])
        self.scan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.scan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.scan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.scan_table.verticalHeader().setVisible(False)
        header = self.scan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.scan_table.itemSelectionChanged.connect(self.node_selected)
        layout.addWidget(self.scan_table, 1)
        return pane

    def build_map_pane(self) -> QFrame:
        pane, layout = self.pane("命名与页面关系")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.region_name = QLineEdit()
        self.aliases = QLineEdit()
        self.region_type = QComboBox()
        self.region_type.addItem("点击区域", "click")
        self.region_type.addItem("页面标志", "anchor")
        self.destination = QComboBox()
        self.destination.setEditable(True)
        self.destination.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("区域名称", self.region_name)
        form.addRow("别名", self.aliases)
        form.addRow("用途", self.region_type)
        form.addRow("点击后页面", self.destination)
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

        self.generated_table = QTableWidget(0, 3)
        self.generated_table.setHorizontalHeaderLabels(["序号", "步骤", "点击坐标"])
        self.generated_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.generated_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.generated_table.verticalHeader().setVisible(False)
        self.generated_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.generated_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.generated_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
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
            self.edit_job_button, self.execute_button,
        ):
            control.setEnabled(not busy)

    def append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {message}")

    def scan(self) -> None:
        if not self.app.adb.serial:
            QMessageBox.warning(self, "ADB 设备", "请先选择已连接的 ADB 设备。")
            return
        self.set_busy(True)
        self.set_state("扫描中", "running")

        def operation():
            try:
                return True, scan_device(self.app.adb)
            except Exception as error:
                return False, str(error)

        def done(result):
            self.set_busy(False)
            ok, value = result
            if not ok:
                self.set_state("失败", "failed")
                QMessageBox.critical(self, "扫描失败", value)
                return
            self.snapshot = value
            self.nodes = value.nodes
            self.populate_nodes()
            detected = self.semantic_map.detect_page(value)
            if detected:
                self.page_name.setCurrentText(detected)
            self.set_state(f"发现 {len(self.nodes)} 个区域", "success")
            self.append_log(
                f"已扫描 {value.width} × {value.height} 界面，共 {len(self.nodes)} 个候选区域"
            )

        self.app.run_async(operation, done)

    def populate_nodes(self) -> None:
        self.scan_table.setRowCount(len(self.nodes))
        for row, node in enumerate(self.nodes):
            left, top, right, bottom = node.bounds
            values = (
                node.label,
                node.source,
                node.class_name.rsplit(".", 1)[-1],
                f"{left},{top} - {right},{bottom}",
            )
            for column, value in enumerate(values):
                self.scan_table.setItem(row, column, QTableWidgetItem(value))

    def node_selected(self) -> None:
        row = self.scan_table.currentRow()
        if 0 <= row < len(self.nodes) and not self.editing_id:
            self.region_name.setText(self.nodes[row].label)

    def selected_node(self) -> UiNode | None:
        row = self.scan_table.currentRow()
        return self.nodes[row] if 0 <= row < len(self.nodes) else None

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
        ratio = bounds_ratio(node, self.snapshot) if node and self.snapshot else existing.bounds_ratio
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
            bounds_ratio=ratio,
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
                "点击" if region.actionable else "标志",
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
        self.region_type.setCurrentIndex(0 if region.actionable else 1)
        self.destination.setCurrentText(region.destination)
        self.scan_table.clearSelection()
        self.set_state("编辑中", "idle")

    def reset_editor(self) -> None:
        self.editing_id = ""
        self.region_name.clear()
        self.aliases.clear()
        self.region_type.setCurrentIndex(0)
        self.destination.setCurrentText("")
        self.scan_table.clearSelection()
        self.set_state("就绪", "idle")

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
            values = (str(row + 1), step.name, f"{step.target[0]}, {step.target[1]}")
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
        self.set_busy(True)
        self.set_state("执行中", "running")
        self.app.set_execution_active(True, "semantic")
        self.append_log(f"命令：{command}")

        def operation():
            try:
                executor = SemanticExecutor(
                    self.app.adb, self.semantic_map, self.log_signal.emit
                )
                return True, executor.execute(command, page_hint)
            except Exception as error:
                return False, str(error)

        def done(result):
            self.app.set_execution_active(False)
            self.set_busy(False)
            ok, value = result
            if ok:
                self.set_state("已完成", "success")
                self.page_name.setCurrentText(value.final_page)
                self.append_log(f"完成：{' → '.join(value.clicks)}")
            else:
                self.set_state("失败", "failed")
                self.append_log(f"失败：{value}")
                QMessageBox.warning(self, "命令执行失败", value)
            self.app.finish_close_if_requested()

        self.app.run_async(operation, done)

    def device_changed(self, serial: str) -> None:
        self.snapshot = None
        self.nodes = []
        self.scan_table.setRowCount(0)
        if serial:
            self.set_state("待扫描", "idle")
