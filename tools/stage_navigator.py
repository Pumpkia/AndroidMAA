"""从真机界面识别并进入奇迹暖暖关卡。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Callable

from semantic_navigator import UiNode, UiSnapshot, scan_device
from stage_model import (
    StageRef,
    parse_chapter_label,
    parse_remaining,
    parse_stage_label,
)


@dataclass(frozen=True)
class StageAction:
    kind: str
    text: str = ""
    direction: str = ""


@dataclass
class ScreenState:
    kind: str
    difficulty: str = ""
    volume: int | None = None
    chapter: int | None = None
    chapter_part: str = ""
    title: str = ""
    remaining: tuple[int, int] | None = None
    visible_chapters: list[str] = field(default_factory=list)
    expanded_chapter: str = ""
    visible_stages: list[str] = field(default_factory=list)
    locked_chapters: list[str] = field(default_factory=list)

    @property
    def stage_ref(self) -> StageRef | None:
        if self.kind != "stage_detail" or self.chapter is None or not self.title:
            return None
        parsed = parse_stage_label(self.title)
        if parsed is None:
            return None
        volume, chapter, branch, stage = parsed
        difficulty = self.difficulty or "少女"
        return StageRef(
            difficulty=difficulty,
            volume=volume,
            chapter=chapter,
            branch=branch,
            stage=stage,
            chapter_part=self.chapter_part,
        )


def node_label(node: UiNode) -> str:
    return (node.text or node.content_desc or "").strip()


def find_nodes(snapshot: UiSnapshot, predicate) -> list[UiNode]:
    return [node for node in snapshot.nodes if predicate(node)]


def find_label(snapshot: UiSnapshot, text: str, clickable: bool | None = None) -> UiNode | None:
    matches = []
    for node in snapshot.nodes:
        label = node_label(node)
        if text not in label:
            continue
        if clickable is not None and node.clickable != clickable:
            continue
        matches.append(node)
    if not matches:
        return None
    matches.sort(key=lambda node: (len(node_label(node)), node.bounds[1], node.bounds[0]))
    return matches[0]


def recognize_stage_screen(snapshot: UiSnapshot) -> ScreenState:
    labels = [node_label(node) for node in snapshot.nodes if node_label(node)]
    joined = " ".join(labels)
    chapters = []
    locked = []
    stages = []
    for node in snapshot.nodes:
        label = node_label(node)
        chapter = parse_chapter_label(label)
        if chapter and label.startswith("第"):
            chapters.append(label.split()[0] if " " in label else _chapter_token(label))
            if _same_row_has(snapshot, node, "暂未解锁"):
                locked.append(chapters[-1])
        stage = parse_stage_label(label)
        if stage:
            stages.append(label)
    difficulty = ""
    for name in ("公主", "少女"):
        node = find_label(snapshot, name)
        if node is not None and getattr(node, "checked", False):
            difficulty = name
            break
    if not difficulty:
        if find_label(snapshot, "切换难度") and find_label(snapshot, "公主"):
            difficulty = "公主"
        elif find_label(snapshot, "切换难度") and find_label(snapshot, "少女"):
            difficulty = "少女"
    remaining = None
    title = ""
    for label in labels:
        parsed = parse_remaining(label)
        if parsed:
            remaining = parsed
        if parse_stage_label(label) and ("支" in label or re.search(r"\d+\s*[-－]\s*\d+", label)):
            if "卷" in label:
                title = label
        chapter_title = parse_chapter_label(label)
        if chapter_title and len(label) > 4 and "切换" not in label:
            if title == "" or label.startswith("第"):
                if "章" in label and "卷" not in label:
                    title = title or label
    expanded = ""
    if stages:
        first = parse_stage_label(stages[0])
        if first:
            expanded = f"第{_chinese_from_int(first[1])}章"
            for chapter in chapters:
                parsed = parse_chapter_label(chapter)
                if parsed and parsed[0] == first[1]:
                    expanded = chapter
                    break
    if remaining or find_label(snapshot, "开始故事") or find_label(snapshot, "过关一次"):
        kind = "stage_detail"
    elif find_label(snapshot, "第一卷") and chapters:
        kind = "chapter_list"
    elif find_label(snapshot, "切换章节") or find_label(snapshot, "切换难度"):
        kind = "chapter_map"
    else:
        kind = "unknown"
    chapter = None
    part = ""
    if title:
        parsed = parse_chapter_label(title)
        if parsed:
            chapter, part = parsed
        staged = parse_stage_label(title)
        if staged:
            chapter = staged[1]
    elif chapters:
        parsed = parse_chapter_label(chapters[0])
        if parsed:
            chapter, part = parsed
    volume = 1 if "第一卷" in joined or "卷 I" in joined or "卷I" in joined else None
    return ScreenState(
        kind=kind,
        difficulty=difficulty,
        volume=volume,
        chapter=chapter,
        chapter_part=part,
        title=title,
        remaining=remaining,
        visible_chapters=_unique(chapters),
        expanded_chapter=expanded,
        visible_stages=_unique(stages),
        locked_chapters=_unique(locked),
    )


def next_stage_action(state: ScreenState, target: StageRef, snapshot: UiSnapshot) -> StageAction | None:
    current = state.stage_ref
    if current is not None and _same_stage(current, target):
        return None
    if state.kind != "chapter_list":
        return StageAction("tap", "切换章节")
    if target.chapter_label in state.locked_chapters:
        raise ValueError(f"{target.chapter_label}尚未解锁")
    if state.difficulty and state.difficulty != target.difficulty:
        return StageAction("tap", target.difficulty)
    if target.chapter_label not in state.visible_chapters:
        numbers = []
        for label in state.visible_chapters:
            parsed = parse_chapter_label(label)
            if parsed:
                numbers.append(parsed[0])
        direction = "down" if numbers and target.chapter < min(numbers) else "up"
        return StageAction("swipe", direction=direction)
    if state.expanded_chapter != target.chapter_label:
        return StageAction("expand", target.chapter_label)
    if any(_stage_matches(label, target) for label in state.visible_stages):
        return StageAction("tap_stage", target.stage_label)
    return StageAction("expand", target.chapter_label)


def apply_stage_action(adb, snapshot: UiSnapshot, action: StageAction) -> None:
    if action.kind == "tap":
        node = _clickable_label(snapshot, action.text)
        if node is None:
            raise RuntimeError(f"界面上找不到「{action.text}」")
        _tap(adb, node)
        return
    if action.kind == "tap_stage":
        node = _find_stage_node(snapshot, action.text)
        if node is None:
            raise RuntimeError(f"界面上找不到关卡「{action.text}」")
        _tap(adb, node)
        return
    if action.kind == "expand":
        node = find_expand_control(snapshot, action.text)
        if node is None:
            raise RuntimeError(f"找不到{action.text}的展开按钮")
        _tap(adb, node)
        return
    if action.kind == "swipe":
        _swipe_list(adb, snapshot, action.direction)
        return
    raise ValueError(f"不支持的关卡动作: {action.kind}")


def is_chapter_expand_label(label: str) -> bool:
    text = (label or "").strip()
    if not text or "完美" in text or "暂未解锁" in text:
        return False
    compact = re.sub(r"\s+", "", text)
    if ">>>" in compact or any(mark in compact for mark in ("▼", "▽", "▲", "△")):
        return True
    match = re.fullmatch(r"(\d+)/(\d+)[▼▽▲△]?", compact)
    if not match:
        return False
    done, total = int(match.group(1)), int(match.group(2))
    return total > 0 and 0 <= done <= total


def find_expand_control(snapshot: UiSnapshot, chapter_label: str) -> UiNode | None:
    chapter = find_label(snapshot, chapter_label)
    if chapter is None:
        return None
    center_y = (chapter.bounds[1] + chapter.bounds[3]) // 2
    matches = []
    for node in snapshot.nodes:
        mid = (node.bounds[1] + node.bounds[3]) // 2
        if abs(mid - center_y) > 90:
            continue
        if node.bounds[2] <= chapter.bounds[0]:
            continue
        if is_chapter_expand_label(node_label(node)):
            matches.append(node)
    if not matches:
        return None
    progress = [node for node in matches if re.search(r"\d+\s*/\s*\d+", node_label(node))]
    chosen = progress or matches
    return max(chosen, key=lambda node: node.bounds[0])


def goto_stage(
    adb,
    target: StageRef,
    *,
    scan: Callable = scan_device,
    pause: Callable[[float], None] = time.sleep,
    attempts: int = 20,
    should_stop: Callable[[], bool] | None = None,
    emit: Callable[[str], None] | None = None,
) -> ScreenState:
    last = None
    for _ in range(attempts):
        if should_stop and should_stop():
            raise RuntimeError("已停止关卡导航")
        snapshot = scan(adb)
        state = recognize_stage_screen(snapshot)
        last = state
        action = next_stage_action(state, target, snapshot)
        if emit:
            if action is None:
                emit(f"已到达 {target.canonical}")
            else:
                emit(f"{state.kind} → {action.kind} {action.text or action.direction}".strip())
        if action is None:
            return state
        apply_stage_action(adb, snapshot, action)
        pause(0.7)
    raise RuntimeError(f"未能进入 {target.canonical}")


def _tap(adb, node: UiNode) -> None:
    x, y = node.action_center
    if hasattr(adb, "inject_tap"):
        adb.inject_tap(x, y)
        return
    adb.shell(["input", "tap", str(x), str(y)])


def _swipe_list(adb, snapshot: UiSnapshot, direction: str) -> None:
    chapters = [node for node in snapshot.nodes if parse_chapter_label(node_label(node))]
    if chapters:
        node = chapters[len(chapters) // 2]
        x, y = node.action_center
    else:
        x, y = snapshot.width // 2, snapshot.height // 2
    delta = 480
    end_y = y - delta if direction == "up" else y + delta
    if hasattr(adb, "inject_swipe"):
        adb.inject_swipe(x, y, x, max(40, end_y), 320)
        return
    adb.shell(["input", "swipe", str(x), str(y), str(x), str(max(40, end_y)), "320"])


def _clickable_label(snapshot: UiSnapshot, text: str) -> UiNode | None:
    node = find_label(snapshot, text, clickable=True)
    if node is not None:
        return node
    node = find_label(snapshot, text)
    if node is None:
        return None
    return node


def _find_stage_node(snapshot: UiSnapshot, stage_label: str) -> UiNode | None:
    target = parse_stage_label(stage_label)
    if target is None:
        return find_label(snapshot, stage_label, clickable=True)
    for node in snapshot.nodes:
        parsed = parse_stage_label(node_label(node))
        if parsed == target:
            return node
    return find_label(snapshot, stage_label)


def _same_row_has(snapshot: UiSnapshot, node: UiNode, text: str) -> bool:
    center_y = (node.bounds[1] + node.bounds[3]) // 2
    for other in snapshot.nodes:
        if text not in node_label(other):
            continue
        mid = (other.bounds[1] + other.bounds[3]) // 2
        if abs(mid - center_y) <= 90:
            return True
    return False


def _chapter_token(label: str) -> str:
    match = re.match(r"(第[一二三四五六七八九十百零\d]+章[上下]?)", label)
    return match.group(1) if match else label


def _chinese_from_int(value: int) -> str:
    from stage_model import to_chinese_int

    return to_chinese_int(value)


def _unique(values: list[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _same_stage(left: StageRef, right: StageRef) -> bool:
    return (
        left.difficulty == right.difficulty
        and left.chapter == right.chapter
        and left.stage == right.stage
        and left.branch == right.branch
        and left.chapter_part == right.chapter_part
    )


def _stage_matches(label: str, target: StageRef) -> bool:
    parsed = parse_stage_label(label)
    if parsed is None:
        return False
    volume, chapter, branch, stage = parsed
    return volume == target.volume and chapter == target.chapter and branch == target.branch and stage == target.stage
