"""Definitions and validation for Qdd custom workbench modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from job_model import JobDocument

MODULE_FORMAT_VERSION = 1
MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
PURPOSES = frozenset({"click", "check", "recognize"})
ACTIONS = frozenset({"Click", "Swipe", "InputText", "ClickKey", "DoNothing"})


@dataclass
class ModuleDefinition:
    """Stable contract shared by recording, semantic navigation and playback."""

    id: str
    name: str
    description: str = ""
    version: int = 1
    allowed_purposes: list[str] = field(
        default_factory=lambda: ["click", "check", "recognize"]
    )
    allowed_actions: list[str] = field(default_factory=lambda: sorted(ACTIONS))
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleDefinition":
        if not isinstance(data, dict):
            raise ValueError("模块定义必须是对象")
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or not MODULE_ID_PATTERN.fullmatch(self.id):
            errors.append("模块 ID 必须是 2-64 位小写字母、数字、下划线或短横线，并以字母开头")
        if not isinstance(self.name, str) or not self.name.strip():
            errors.append("模块名称不能为空")
        elif len(self.name.strip()) > 80:
            errors.append("模块名称不能超过 80 个字符")
        if not isinstance(self.description, str) or len(self.description) > 500:
            errors.append("模块说明不能超过 500 个字符")
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 1
        ):
            errors.append("模块版本必须是正整数")
        purposes = self.allowed_purposes
        if (
            not isinstance(purposes, list)
            or not purposes
            or any(not isinstance(item, str) or item not in PURPOSES for item in purposes)
        ):
            errors.append("允许的语义用途只能源于 click、check、recognize，且至少选择一项")
        elif len(set(purposes)) != len(purposes):
            errors.append("允许的语义用途不能重复")
        actions = self.allowed_actions
        if (
            not isinstance(actions, list)
            or not actions
            or any(not isinstance(item, str) or item not in ACTIONS for item in actions)
        ):
            errors.append("允许的动作包含不支持的类型，且至少选择一项")
        elif len(set(actions)) != len(actions):
            errors.append("允许的动作不能重复")
        if not isinstance(self.enabled, bool):
            errors.append("模块启用状态必须是布尔值")
        return errors

    def validate_document(self, document: JobDocument) -> list[str]:
        errors = self.validate()
        if not isinstance(document, JobDocument):
            return ["待校验对象必须是 JobDocument"]
        if not isinstance(document.module_id, str):
            return ["用例绑定的模块 ID 必须是字符串"]
        if document.module_id and document.module_id != self.id:
            errors.append(f"用例绑定的模块不是 {self.name}")
        for index, step in enumerate(document.steps, start=1):
            if step.semantic_purpose and step.semantic_purpose not in self.allowed_purposes:
                errors.append(f"第 {index} 步的语义用途不在模块允许范围内")
            if step.action not in self.allowed_actions:
                errors.append(f"第 {index} 步的动作不在模块允许范围内")
        return errors


BUILTIN_MODULES = (
    ModuleDefinition("recording", "用例录制", "手动标记坐标、模板和输入步骤"),
    ModuleDefinition(
        "semantic",
        "语义导航",
        "通过区域名称生成 OCR 语义步骤",
        allowed_purposes=["click", "check", "recognize"],
        allowed_actions=["Click", "DoNothing"],
    ),
    ModuleDefinition("custom", "自定义模块", "由用户定义用途和动作边界"),
)


class ModuleRegistry:
    """Load, validate and persist built-in plus user-defined module definitions."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.modules: dict[str, ModuleDefinition] = {
            module.id: ModuleDefinition(**asdict(module)) for module in BUILTIN_MODULES
        }
        self.builtin_ids = frozenset(module.id for module in BUILTIN_MODULES)
        self.load_error = ""
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("模块配置顶层必须是对象")
            if payload.get("format_version") != MODULE_FORMAT_VERSION:
                raise ValueError("不支持的模块定义版本")
            items = payload.get("modules", [])
            if not isinstance(items, list):
                raise ValueError("modules 必须是数组")
            loaded: dict[str, ModuleDefinition] = {}
            for item in items:
                module = ModuleDefinition.from_dict(item)
                errors = module.validate()
                if module.id in self.builtin_ids:
                    raise ValueError(f"内置模块不能覆盖: {module.id}")
                if errors:
                    raise ValueError(f"模块 {module.id or '<unknown>'} 无效: " + ";".join(errors))
                if module.id in loaded:
                    raise ValueError(f"模块 ID 重复: {module.id}")
                loaded[module.id] = module
            self.modules.update(loaded)
        except Exception as error:
            self.load_error = str(error)

    def list(self) -> list[ModuleDefinition]:
        return sorted(
            (module for module in self.modules.values() if module.enabled),
            key=lambda item: (item.name, item.id),
        )

    def get(self, module_id: str) -> ModuleDefinition | None:
        return self.modules.get(module_id)

    def upsert(self, module: ModuleDefinition) -> None:
        if not isinstance(module, ModuleDefinition):
            raise TypeError("模块定义必须是 ModuleDefinition")
        errors = module.validate()
        if module.id in self.builtin_ids:
            raise ValueError("内置模块不能覆盖")
        if errors:
            raise ValueError("\n".join(errors))
        self.modules[module.id] = module
        self.save()

    def remove(self, module_id: str) -> None:
        if module_id in {module.id for module in BUILTIN_MODULES}:
            raise ValueError("内置模块不能删除")
        self.modules.pop(module_id, None)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        builtin_ids = {item.id for item in BUILTIN_MODULES}
        payload = {
            "format_version": MODULE_FORMAT_VERSION,
            "modules": [
                asdict(module)
                for module in sorted(
                    self.modules.values(), key=lambda item: (item.name, item.id)
                )
                if module.id not in builtin_ids
            ],
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def validate_document(self, document: JobDocument) -> list[str]:
        if not isinstance(document, JobDocument):
            return ["待校验对象必须是 JobDocument"]
        if not isinstance(document.module_id, str):
            return ["用例绑定的模块 ID 必须是字符串"]
        if not document.module_id:
            return []
        module = self.get(document.module_id)
        if module is None:
            return [f"找不到用例绑定的模块: {document.module_id}"]
        if not module.enabled:
            return [f"用例绑定的模块已停用: {document.module_id}"]
        if document.module_version != module.version:
            return [f"用例模块版本 {document.module_version} 与当前定义 {module.version} 不一致"]
        return module.validate_document(document)