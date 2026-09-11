"""奇迹暖暖刷关记忆：目标衣服、材料层级、缺口与每日通关次数。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


MEMORY_FORMAT_VERSION = 1


@dataclass
class ClothingItem:
    id: str
    name: str
    category: str = ""
    needed: int = 1
    owned: int = 0
    stage: str = ""
    daily_limit: int = 3
    parent_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClothingItem":
        if not isinstance(data, dict):
            raise ValueError("衣服记录必须是对象")
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})

    @property
    def missing(self) -> int:
        needed = self.needed if isinstance(self.needed, int) and not isinstance(self.needed, bool) else 0
        owned = self.owned if isinstance(self.owned, int) and not isinstance(self.owned, bool) else 0
        return max(0, needed - owned)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or not self.id.strip():
            errors.append("衣服 ID 不能为空")
        if not isinstance(self.name, str) or not self.name.strip():
            errors.append("衣服名称不能为空")
        elif len(self.name.strip()) > 80:
            errors.append("衣服名称不能超过 80 个字符")
        if not isinstance(self.category, str) or len(self.category) > 40:
            errors.append("部位不能超过 40 个字符")
        if not isinstance(self.stage, str) or len(self.stage) > 80:
            errors.append("关卡名称不能超过 80 个字符")
        if not isinstance(self.parent_id, str):
            errors.append("上级衣服 ID 必须是字符串")
        for label, value, minimum in (
            ("需求数量", self.needed, 1),
            ("已有数量", self.owned, 0),
            ("每日次数", self.daily_limit, 1),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                errors.append(f"{label}必须是不小于 {minimum} 的整数")
            elif value > 9999:
                errors.append(f"{label}不能超过 9999")
        return errors


@dataclass
class ClothingLedger:
    path: Path
    items: list[ClothingItem] = field(default_factory=list)
    daily_date: str = ""
    stage_usage: dict[str, int] = field(default_factory=dict)
    load_error: str = ""
    today: Callable[[], str] | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()
        self.ensure_today()

    def current_day(self) -> str:
        if self.today is not None:
            return self.today()
        return date.today().isoformat()

    def ensure_today(self) -> bool:
        day = self.current_day()
        if self.daily_date == day:
            return False
        self.daily_date = day
        self.stage_usage = {}
        return True

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("刷关记忆顶层必须是对象")
            if payload.get("format_version") != MEMORY_FORMAT_VERSION:
                raise ValueError("不支持的刷关记忆版本")
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise ValueError("items 必须是数组")
            loaded: list[ClothingItem] = []
            seen: set[str] = set()
            for item in items:
                clothing = ClothingItem.from_dict(item)
                errors = clothing.validate()
                if errors:
                    raise ValueError(f"衣服 {clothing.id or '<unknown>'} 无效: " + ";".join(errors))
                if clothing.id in seen:
                    raise ValueError(f"衣服 ID 重复: {clothing.id}")
                seen.add(clothing.id)
                loaded.append(clothing)
            usage = payload.get("stage_usage", {})
            if not isinstance(usage, dict) or any(
                not isinstance(key, str)
                or not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for key, value in usage.items()
            ):
                raise ValueError("stage_usage 必须是非负整数映射")
            daily_date = payload.get("daily_date", "")
            if not isinstance(daily_date, str):
                raise ValueError("daily_date 必须是字符串")
            parent_ids = {item.parent_id for item in loaded if item.parent_id}
            known = {item.id for item in loaded}
            missing_parents = sorted(parent_ids - known)
            if missing_parents:
                raise ValueError("找不到上级衣服: " + ", ".join(missing_parents))
            self.items = loaded
            self.daily_date = daily_date
            self.stage_usage = {key: int(value) for key, value in usage.items()}
            self._assert_no_cycles()
        except Exception as error:
            self.load_error = str(error)
            self.items = []
            self.daily_date = ""
            self.stage_usage = {}

    def save(self) -> None:
        errors = []
        for item in self.items:
            errors.extend(item.validate())
        if errors:
            raise ValueError("\n".join(errors))
        self._assert_no_cycles()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": MEMORY_FORMAT_VERSION,
            "daily_date": self.daily_date,
            "stage_usage": dict(sorted(self.stage_usage.items())),
            "items": [asdict(item) for item in self.items],
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get(self, item_id: str) -> ClothingItem | None:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def roots(self) -> list[ClothingItem]:
        return sorted(
            (item for item in self.items if not item.parent_id),
            key=lambda item: item.name,
        )

    def children_of(self, parent_id: str) -> list[ClothingItem]:
        return sorted(
            (item for item in self.items if item.parent_id == parent_id),
            key=lambda item: item.name,
        )

    def layer(self, item_id: str) -> int:
        depth = 0
        current = self.get(item_id)
        seen: set[str] = set()
        while current is not None and current.parent_id:
            if current.id in seen:
                break
            seen.add(current.id)
            depth += 1
            current = self.get(current.parent_id)
        return depth

    def layer_label(self, item_id: str) -> str:
        depth = self.layer(item_id)
        if depth <= 0:
            return "目标"
        return f"{depth}级材料"

    def upsert(self, item: ClothingItem) -> ClothingItem:
        errors = item.validate()
        if item.parent_id:
            if item.parent_id == item.id:
                errors.append("衣服不能作为自己的材料")
            elif self.get(item.parent_id) is None:
                errors.append("找不到上级衣服")
        if errors:
            raise ValueError("\n".join(errors))
        existing = self.get(item.id)
        if existing is None:
            self.items.append(item)
        else:
            index = self.items.index(existing)
            self.items[index] = item
        try:
            self._assert_no_cycles()
        except ValueError:
            if existing is None:
                self.items.pop()
            else:
                self.items[index] = existing
            raise
        self.save()
        return item

    def add_item(
        self,
        name: str,
        category: str = "",
        needed: int = 1,
        owned: int = 0,
        stage: str = "",
        daily_limit: int = 3,
        parent_id: str = "",
    ) -> ClothingItem:
        return self.upsert(
            ClothingItem(
                id=uuid4().hex,
                name=name.strip(),
                category=category.strip(),
                needed=needed,
                owned=owned,
                stage=stage.strip(),
                daily_limit=daily_limit,
                parent_id=parent_id,
            )
        )

    def remove(self, item_id: str) -> None:
        drop = {item_id}
        changed = True
        while changed:
            changed = False
            for item in self.items:
                if item.parent_id in drop and item.id not in drop:
                    drop.add(item.id)
                    changed = True
        self.items = [item for item in self.items if item.id not in drop]
        self.save()

    def gain(self, item_id: str, count: int = 1) -> ClothingItem:
        item = self.get(item_id)
        if item is None:
            raise ValueError("找不到衣服记录")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("获得数量必须是正整数")
        item.owned += count
        self.save()
        return item

    def stage_limit(self, stage: str) -> int:
        limits = [item.daily_limit for item in self.items if item.stage == stage]
        return max(limits) if limits else 3

    def used_today(self, stage: str) -> int:
        self.ensure_today()
        return int(self.stage_usage.get(stage, 0))

    def remaining(self, stage: str, daily_limit: int | None = None) -> int:
        if not stage.strip():
            return 0
        limit = self.stage_limit(stage) if daily_limit is None else daily_limit
        return max(0, limit - self.used_today(stage))

    def record_clear(self, stage: str) -> int:
        stage = stage.strip()
        if not stage:
            raise ValueError("请先填写关卡")
        self.ensure_today()
        remaining = self.remaining(stage)
        if remaining <= 0:
            raise ValueError(f"{stage} 今日通过次数已用完")
        self.stage_usage[stage] = self.used_today(stage) + 1
        self.save()
        return self.remaining(stage)

    def farm_queue(self) -> list[tuple[ClothingItem, int, int]]:
        self.ensure_today()
        rows = []
        for item in self.items:
            if item.missing <= 0 or not item.stage.strip():
                continue
            rows.append((item, item.missing, self.remaining(item.stage)))
        rows.sort(
            key=lambda row: (
                row[2] <= 0,
                -self.layer(row[0].id),
                -row[1],
                row[0].name,
            )
        )
        return rows

    def recommend(self) -> str:
        queue = self.farm_queue()
        if not queue:
            if any(item.missing > 0 for item in self.items):
                return "还有缺口，但没有填写关卡"
            return "当前没有待刷衣服"
        item, missing, remaining = queue[0]
        if remaining <= 0:
            return f"今日次数已用完，优先关卡 {item.stage} 仍差 {missing} 件「{item.name}」"
        return f"今日优先刷 {item.stage} · {item.name} 还差 {missing} 件 · 剩余 {remaining} 次"

    def _assert_no_cycles(self) -> None:
        known = {item.id: item.parent_id for item in self.items}
        for item_id in known:
            seen: set[str] = set()
            current = item_id
            while current:
                if current in seen:
                    raise ValueError("衣服层级不能成环")
                seen.add(current)
                current = known.get(current, "")
