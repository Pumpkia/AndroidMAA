"""Data model and Maa Pipeline exporter for QQ App jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


JOB_FORMAT_VERSION = 3
SUPPORTED_FORMAT_VERSIONS = {1, 2, JOB_FORMAT_VERSION}
SUPPORTED_RECOGNITIONS = {"DirectHit", "TemplateMatch", "OCR"}
SUPPORTED_ACTIONS = {"Click", "Swipe", "InputText", "ClickKey", "DoNothing"}
SUPPORTED_SEMANTIC_PURPOSES = {"click", "check", "recognize"}


def _is_rectangle(value: list[int] | None) -> bool:
    return bool(
        value
        and len(value) == 4
        and all(isinstance(item, int) for item in value)
        and value[0] >= 0
        and value[1] >= 0
        and value[2] > 0
        and value[3] > 0
    )


def _is_ratio_rectangle(value: list[float] | None) -> bool:
    return bool(
        value
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
        and all(0 <= float(item) <= 1 for item in value)
        and float(value[0]) < float(value[2])
        and float(value[1]) < float(value[3])
    )


def _is_device_size(value: list[int] | None) -> bool:
    return bool(
        value
        and len(value) == 2
        and all(isinstance(item, int) and item > 0 for item in value)
    )


def ratio_to_rect(ratio: list[float], device_size: list[int]) -> list[int]:
    if not _is_ratio_rectangle(ratio):
        raise ValueError(
            "Normalized bounds must be [left, top, right, bottom] within 0..1"
        )
    if not _is_device_size(device_size):
        raise ValueError("Device size must be [width, height] with positive values")
    width, height = device_size
    left = min(width - 1, max(0, round(float(ratio[0]) * width)))
    top = min(height - 1, max(0, round(float(ratio[1]) * height)))
    right = min(width, max(left + 1, round(float(ratio[2]) * width)))
    bottom = min(height, max(top + 1, round(float(ratio[3]) * height)))
    return [left, top, right - left, bottom - top]


def rect_to_ratio(rect: list[int], device_size: list[int]) -> list[float]:
    if not _is_rectangle(rect):
        raise ValueError("Bounds must be [x, y, width, height] with positive size")
    if not _is_device_size(device_size):
        raise ValueError("Device size must be [width, height] with positive values")
    width, height = device_size
    x, y, rect_width, rect_height = rect
    return [
        round(x / width, 6),
        round(y / height, 6),
        round((x + rect_width) / width, 6),
        round((y + rect_height) / height, 6),
    ]


def safe_name(value: str, fallback: str = "job") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value.strip())
    return cleaned.strip("_") or fallback

SMART_CATEGORIES = (
    "账号与登录",
    "消息与社交",
    "设置与权限",
    "支付与钱包",
    "表单输入",
    "通用流程",
)


def suggest_category(name: str, steps: list["JobStep"]) -> str:
    content = " ".join([name, *(step.name for step in steps), *(step.expected for step in steps)])
    rules = (
        ("账号与登录", ("登录", "账号", "密码", "验证码", "注册", "切换账号")),
        ("消息与社交", ("消息", "聊天", "好友", "群", "联系人", "发送")),
        ("设置与权限", ("设置", "权限", "隐私", "通知", "安全", "开关")),
        ("支付与钱包", ("支付", "钱包", "红包", "转账", "收款")),
    )
    for category, keywords in rules:
        if any(keyword in content for keyword in keywords):
            return category
    if any(step.action == "InputText" for step in steps):
        return "表单输入"
    return "通用流程"

@dataclass
class JobStep:
    name: str
    recognition: str = "TemplateMatch"
    action: str = "Click"
    template: str = ""
    roi: list[int] | None = None
    expected: str = ""
    threshold: float = 0.8
    target: list[int] | None = None
    swipe_end: list[int] | None = None
    input_text: str = ""
    key: int = 4
    duration: int = 300
    pre_delay: int = 0
    post_delay: int = 500
    semantic_purpose: str = ""
    roi_ratio: list[float] | None = None
    target_ratio: list[float] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobStep":
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("步骤名称不能为空")
        if self.recognition not in SUPPORTED_RECOGNITIONS:
            errors.append(f"不支持的识别类型: {self.recognition}")
        if self.action not in SUPPORTED_ACTIONS:
            errors.append(f"不支持的动作类型: {self.action}")
        if self.semantic_purpose and self.semantic_purpose not in SUPPORTED_SEMANTIC_PURPOSES:
            errors.append(
                f"不支持的语义用途: {self.semantic_purpose}，"
                "仅支持 click、check、recognize"
            )
        elif self.semantic_purpose:
            if self.recognition != "OCR":
                errors.append("语义步骤必须使用 OCR 识别")
            if not _is_rectangle(self.roi):
                errors.append("语义步骤必须包含 [x, y, 宽, 高] 格式的识别区域")
            if self.semantic_purpose == "click":
                if self.action != "Click":
                    errors.append("click 语义用途必须使用 Click 动作")
                if not _is_rectangle(self.target):
                    errors.append("click 语义用途必须包含 [x, y, 宽, 高] 格式的点击区域")
            elif self.action != "DoNothing":
                errors.append(f"{self.semantic_purpose} 语义用途必须使用 DoNothing 动作")
        if self.roi_ratio is not None and not _is_ratio_rectangle(self.roi_ratio):
            errors.append(
                "roi_ratio must be [left, top, right, bottom] within 0..1"
            )
        if self.target_ratio is not None and not _is_ratio_rectangle(self.target_ratio):
            errors.append(
                "target_ratio must be [left, top, right, bottom] within 0..1"
            )
        if self.recognition == "TemplateMatch" and not self.template:
            errors.append("模板匹配步骤必须包含模板图片")
        if self.recognition == "OCR" and not self.expected.strip():
            errors.append("OCR 步骤必须填写期望文字")
        if self.action == "Click" and self.recognition == "DirectHit" and not self.target:
            errors.append("直接点击步骤必须选择点击坐标")
        if self.action == "Swipe" and (not self.target or not self.swipe_end):
            errors.append("滑动步骤必须选择起点和终点")
        if self.action == "InputText" and not self.input_text:
            errors.append("输入文本步骤不能为空")
        if not 0 <= self.threshold <= 1:
            errors.append("匹配阈值必须在 0 到 1 之间")
        if self.duration < 0 or self.pre_delay < 0 or self.post_delay < 0:
            errors.append("持续时间和步骤延迟不能为负数")
        return errors

    def to_pipeline_node(
        self,
        next_name: str | None,
        runtime_device_size: list[int] | None = None,
        source_device_size: list[int] | None = None,
    ) -> dict[str, Any]:
        roi = self.roi
        target = self.target
        if self.semantic_purpose and runtime_device_size is not None:
            roi_ratio = self.roi_ratio
            if (
                roi_ratio is None
                and roi is not None
                and _is_device_size(source_device_size)
            ):
                roi_ratio = rect_to_ratio(roi, source_device_size)
            if roi_ratio is not None:
                roi = ratio_to_rect(roi_ratio, runtime_device_size)

            target_ratio = self.target_ratio
            if (
                target_ratio is None
                and target is not None
                and _is_device_size(source_device_size)
            ):
                target_ratio = rect_to_ratio(target, source_device_size)
            if target_ratio is not None:
                target = ratio_to_rect(target_ratio, runtime_device_size)

        node: dict[str, Any] = {"recognition": self.recognition}
        if roi:
            node["roi"] = roi
        if self.recognition == "TemplateMatch":
            node["template"] = self.template
            node["threshold"] = self.threshold
        elif self.recognition == "OCR":
            node["expected"] = self.expected

        node["action"] = self.action
        if self.action == "Click" and target:
            node["target"] = target
        elif self.action == "Swipe":
            node["begin"] = self.target
            node["end"] = self.swipe_end
            node["duration"] = self.duration
        elif self.action == "InputText":
            node["input_text"] = self.input_text
        elif self.action == "ClickKey":
            node["key"] = self.key

        if self.pre_delay:
            node["pre_delay"] = self.pre_delay
        if self.post_delay:
            node["post_delay"] = self.post_delay
        node["next"] = [next_name] if next_name else []
        return node


@dataclass
class JobDocument:
    name: str = "QQ作业"
    category: str = "默认"
    prerequisites: list[str] = field(default_factory=list)
    device_size: list[int] = field(default_factory=lambda: [720, 1600])
    steps: list[JobStep] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "JobDocument":
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get("format_version") not in SUPPORTED_FORMAT_VERSIONS:
            raise ValueError("不支持的作业文件版本")
        return cls(
            name=data.get("name", "QQ作业"),
            category=data.get("category", "默认"),
            prerequisites=data.get("prerequisites", []),
            device_size=data.get("device_size", [720, 1600]),
            steps=[JobStep.from_dict(item) for item in data.get("steps", [])],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": JOB_FORMAT_VERSION,
            "name": self.name,
            "category": self.category,
            "prerequisites": self.prerequisites,
            "device_size": self.device_size,
            "steps": [asdict(step) for step in self.steps],
        }
        with path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("作业名称不能为空")
        if not self.category.strip():
            errors.append("作业分类不能为空")
        if len(self.prerequisites) != len(set(self.prerequisites)):
            errors.append("前置用例不能重复")
        seen: set[str] = set()
        for index, step in enumerate(self.steps, start=1):
            if step.name in seen:
                errors.append(f"第 {index} 步名称重复: {step.name}")
            seen.add(step.name)
            errors.extend(f"第 {index} 步: {message}" for message in step.validate())
        return errors

    def resolve_prerequisites(self, jobs_dir: Path) -> list["JobDocument"]:
        root = jobs_dir.resolve()
        resolved: list[JobDocument] = []
        visited: set[Path] = set()
        stack: list[Path] = []

        def visit(reference: str) -> None:
            path = (root / reference).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"前置用例路径越界: {reference}")
            if path in stack:
                cycle = " -> ".join(item.name for item in [*stack, path])
                raise ValueError(f"检测到前置用例循环依赖: {cycle}")
            if path in visited:
                return
            if not path.is_file():
                raise ValueError(f"找不到前置用例: {reference}")
            stack.append(path)
            document = JobDocument.load(path)
            for child in document.prerequisites:
                visit(child)
            stack.pop()
            visited.add(path)
            resolved.append(document)

        for reference in self.prerequisites:
            visit(reference)
        return resolved

    def to_pipeline(
        self,
        prerequisite_documents: list["JobDocument"] | None = None,
        runtime_device_size: list[int] | None = None,
    ) -> dict[str, Any]:
        if runtime_device_size is not None and not _is_device_size(runtime_device_size):
            raise ValueError("Runtime device size must contain positive width and height")

        documents = [*(prerequisite_documents or []), self]
        all_errors: list[str] = []
        for document in documents:
            all_errors.extend(f"{document.name}: {error}" for error in document.validate())
        if all_errors:
            raise ValueError("\n".join(all_errors))

        entry_name = safe_name(self.name, "QQJob")
        named_steps: list[tuple[str, JobStep, list[int]]] = []
        names = {entry_name}
        for document in documents:
            prefix = "" if document is self else f"{safe_name(document.name)}__"
            for step in document.steps:
                node_name = f"{prefix}{step.name}"
                if node_name in names:
                    raise ValueError(f"导出节点名称冲突: {node_name}")
                names.add(node_name)
                named_steps.append((node_name, step, document.device_size))

        pipeline: dict[str, Any] = {
            entry_name: {
                "recognition": "DirectHit",
                "action": "DoNothing",
                "next": [named_steps[0][0]] if named_steps else [],
            }
        }
        for index, (node_name, step, source_device_size) in enumerate(named_steps):
            next_name = named_steps[index + 1][0] if index + 1 < len(named_steps) else None
            pipeline[node_name] = step.to_pipeline_node(
                next_name,
                runtime_device_size=runtime_device_size,
                source_device_size=source_device_size,
            )
        return pipeline

    def export_pipeline(self, path: Path, jobs_dir: Path | None = None) -> None:
        prerequisites = self.resolve_prerequisites(jobs_dir) if self.prerequisites and jobs_dir else []
        if self.prerequisites and jobs_dir is None:
            raise ValueError("导出含前置用例的作业时必须提供作业库目录")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as stream:
            json.dump(self.to_pipeline(prerequisites), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
