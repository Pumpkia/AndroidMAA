"""奇迹暖暖仓库账本：只认 jobs/clothing_memory.json。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


MEMORY_FORMAT_VERSION = 2
JOB_NAV = "nav_8z3"
JOB_FARM = "farm_8z3_once"
JOB_EVO_HUA = "evo_base_to_hua"
JOB_EVO_RARE = "evo_hua_to_rare"
JOB_WAREHOUSE = "warehouse_nz_rare"
DONE = "DONE"
NO_TRIES = "NO_TRIES"
TIER_LABELS = {"base": "原貌", "hua": "华丽", "rare": "珍稀"}
DEFAULT_EVO_NEED = {"hua": 5, "rare": 4}


def nz_template() -> dict[str, Any]:
    return {
        "format_version": MEMORY_FORMAT_VERSION,
        "target": {
            "id": "NZ-003",
            "name": "姹紫嫣红·珍稀",
            "asset": "assets/dress/nz_rare.png",
        },
        "chain": [
            {
                "id": "NZ-001",
                "name": "姹紫嫣红",
                "tier": "base",
                "keep": 1,
                "have": 0,
                "asset": "assets/dress/nz_base.png",
                "source": {
                    "type": "stage",
                    "stage": "8-支3",
                    "cost_hp": 6,
                    "daily_limit": 3,
                },
            },
            {
                "id": "NZ-002",
                "name": "姹紫嫣红·华丽",
                "tier": "hua",
                "keep": 1,
                "have": 0,
                "asset": "assets/dress/nz_hua.png",
                "source": {
                    "type": "evolve",
                    "job": JOB_EVO_HUA,
                    "gold": 4000,
                    "need": 5,
                },
            },
            {
                "id": "NZ-003",
                "name": "姹紫嫣红·珍稀",
                "tier": "rare",
                "keep": 0,
                "have": 0,
                "asset": "assets/dress/nz_rare.png",
                "source": {
                    "type": "evolve",
                    "job": JOB_EVO_RARE,
                    "gold": 7000,
                    "need": 4,
                },
            },
        ],
        "daily": {"stage": "8-支3", "remain": 3, "limit": 3, "date": ""},
        "gap": {"consumable": "have - keep"},
    }


@dataclass
class ItemSource:
    type: str = "stage"
    stage: str = ""
    cost_hp: int = 0
    daily_limit: int = 3
    job: str = ""
    gold: int = 0
    need: int = 0

    @classmethod
    def from_dict(cls, data: Any) -> "ItemSource":
        if not isinstance(data, dict):
            return cls()
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})


@dataclass
class ChainPiece:
    id: str
    name: str
    tier: str = "base"
    keep: int = 0
    have: int = 0
    source: ItemSource = field(default_factory=ItemSource)
    asset: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChainPiece":
        if not isinstance(data, dict):
            raise ValueError("衣服记录必须是对象")
        payload = dict(data)
        payload["source"] = ItemSource.from_dict(data.get("source", {}))
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in payload.items() if key in fields})

    @property
    def consumable(self) -> int:
        return max(0, int(self.have) - int(self.keep))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or not self.id.strip():
            errors.append("衣服 ID 不能为空")
        if not isinstance(self.name, str) or not self.name.strip():
            errors.append("衣服名称不能为空")
        if self.tier not in TIER_LABELS:
            errors.append("衣服层级必须是 base、hua 或 rare")
        for label, value, minimum in (
            ("保留数量", self.keep, 0),
            ("已有数量", self.have, 0),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                errors.append(f"{label}必须是不小于 {minimum} 的整数")
        if self.source.type not in {"stage", "evolve"}:
            errors.append("来源类型必须是 stage 或 evolve")
        return errors


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

    @property
    def missing(self) -> int:
        return max(0, self.needed - self.owned)


@dataclass
class ClothingLedger:
    path: Path
    target: dict[str, str] = field(default_factory=dict)
    chain: list[ChainPiece] = field(default_factory=list)
    daily: dict[str, Any] = field(default_factory=dict)
    items: list[ClothingItem] = field(default_factory=list)
    load_error: str = ""
    today: Callable[[], str] | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()
        self.ensure_today()
        self._rebuild_items()

    def current_day(self) -> str:
        if self.today is not None:
            return self.today()
        return date.today().isoformat()

    def ensure_today(self) -> bool:
        day = self.current_day()
        current = str(self.daily.get("date") or "")
        if current == day:
            return False
        limit = int(self.daily.get("limit") or 3)
        self.daily["date"] = day
        self.daily["remain"] = limit
        self.daily["limit"] = limit
        return True

    def load(self) -> None:
        if not self.path.exists():
            payload = nz_template()
            self._apply_payload(payload)
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("刷关记忆顶层必须是对象")
            version = payload.get("format_version")
            if version != MEMORY_FORMAT_VERSION:
                raise ValueError("不支持的刷关记忆版本")
            self._apply_payload(payload)
        except Exception as error:
            self.load_error = str(error)
            self.target = {}
            self.chain = []
            self.daily = {"stage": "", "remain": 0, "limit": 3, "date": ""}
            self.items = []

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        target = payload.get("target") or {}
        if not isinstance(target, dict):
            raise ValueError("target 必须是对象")
        chain = payload.get("chain", [])
        if not isinstance(chain, list):
            raise ValueError("chain 必须是数组")
        loaded: list[ChainPiece] = []
        seen: set[str] = set()
        for item in chain:
            piece = ChainPiece.from_dict(item)
            errors = piece.validate()
            if errors:
                raise ValueError(f"衣服 {piece.id or '<unknown>'} 无效: " + ";".join(errors))
            if piece.id in seen:
                raise ValueError(f"衣服 ID 重复: {piece.id}")
            seen.add(piece.id)
            loaded.append(piece)
        daily = payload.get("daily") or {}
        if not isinstance(daily, dict):
            raise ValueError("daily 必须是对象")
        self.target = {
            "id": str(target.get("id") or ""),
            "name": str(target.get("name") or ""),
            "asset": str(target.get("asset") or ""),
        }
        self.chain = loaded
        self.daily = {
            "stage": str(daily.get("stage") or ""),
            "remain": int(daily.get("remain") or 0),
            "limit": int(daily.get("limit") or 3),
            "date": str(daily.get("date") or ""),
        }

    def save(self) -> None:
        errors: list[str] = []
        for piece in self.chain:
            errors.extend(piece.validate())
        if errors:
            raise ValueError("\n".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": MEMORY_FORMAT_VERSION,
            "target": self.target,
            "chain": [
                {
                    "id": piece.id,
                    "name": piece.name,
                    "tier": piece.tier,
                    "keep": piece.keep,
                    "have": piece.have,
                    "asset": piece.asset,
                    "source": asdict(piece.source),
                }
                for piece in self.chain
            ],
            "daily": dict(self.daily),
            "gap": {"consumable": "have - keep"},
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        items: list[ClothingItem] = []
        previous = ""
        for piece in self.chain:
            need = piece.source.need if piece.source.type == "evolve" else max(piece.keep, 1)
            items.append(
                ClothingItem(
                    id=piece.id,
                    name=piece.name,
                    category=TIER_LABELS.get(piece.tier, piece.tier),
                    needed=need if need else 1,
                    owned=piece.have,
                    stage=piece.source.stage if piece.source.type == "stage" else "",
                    daily_limit=int(self.daily.get("limit") or 3),
                    parent_id=previous,
                )
            )
            previous = piece.id
        self.items = items

    def piece(self, item_id: str) -> ChainPiece | None:
        for item in self.chain:
            if item.id == item_id:
                return item
        return None

    def piece_by_tier(self, tier: str) -> ChainPiece | None:
        for item in self.chain:
            if item.tier == tier:
                return item
        return None

    def get(self, item_id: str) -> ClothingItem | None:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def roots(self) -> list[ClothingItem]:
        return [item for item in self.items if not item.parent_id]

    def children_of(self, parent_id: str) -> list[ClothingItem]:
        return [item for item in self.items if item.parent_id == parent_id]

    def layer(self, item_id: str) -> int:
        for index, item in enumerate(self.chain):
            if item.id == item_id:
                return index
        return 0

    def layer_label(self, item_id: str) -> str:
        piece = self.piece(item_id)
        if piece is None:
            return "目标"
        return TIER_LABELS.get(piece.tier, piece.tier)

    def evo_need(self, piece: ChainPiece) -> int:
        if piece.source.need and piece.source.need > 0:
            return piece.source.need
        return DEFAULT_EVO_NEED.get(piece.tier, 1)

    def next_job(self) -> str:
        self.ensure_today()
        rare = self.piece_by_tier("rare")
        if rare is not None and rare.have >= 1:
            return DONE
        hua = self.piece_by_tier("hua")
        if rare is not None and hua is not None and hua.consumable >= self.evo_need(rare):
            return JOB_EVO_RARE
        base = self.piece_by_tier("base")
        if hua is not None and base is not None and base.consumable >= self.evo_need(hua):
            return JOB_EVO_HUA
        if int(self.daily.get("remain") or 0) <= 0:
            return NO_TRIES
        return JOB_FARM

    def recommend(self) -> str:
        decision = self.next_job()
        remain = int(self.daily.get("remain") or 0)
        stage = str(self.daily.get("stage") or "")
        if decision == DONE:
            return f"{self.target.get('name') or '目标'} 已完成"
        if decision == NO_TRIES:
            return f"{stage or '今日'} 次数已用完"
        if decision == JOB_EVO_RARE:
            return "华丽够用，跑 evo_hua_to_rare"
        if decision == JOB_EVO_HUA:
            return "原貌够用，跑 evo_base_to_hua"
        return f"今日优先刷 {stage} · 剩余 {remain} 次 · 跑 {JOB_FARM}"

    def set_have(self, item_id: str, have: int) -> ChainPiece:
        piece = self.piece(item_id)
        if piece is None:
            raise ValueError("找不到衣服记录")
        if not isinstance(have, int) or isinstance(have, bool) or have < 0:
            raise ValueError("已有数量必须是非负整数")
        piece.have = have
        self.save()
        return piece

    def add_have(self, item_id: str, count: int = 1) -> ChainPiece:
        piece = self.piece(item_id)
        if piece is None:
            raise ValueError("找不到衣服记录")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("获得数量必须是正整数")
        piece.have += count
        self.save()
        return piece

    def set_evolve_need(self, item_id: str, need: int) -> ChainPiece:
        piece = self.piece(item_id)
        if piece is None:
            raise ValueError("找不到衣服记录")
        if not isinstance(need, int) or isinstance(need, bool) or need < 1:
            raise ValueError("进化需求必须是正整数")
        piece.source.need = need
        self.save()
        return piece

    def apply_job_success(self, job: str, drop_count: int = 1) -> str:
        self.ensure_today()
        if job in {JOB_NAV, "nav"}:
            return JOB_NAV
        if job in {JOB_FARM, "farm"}:
            base = self.piece_by_tier("base")
            if base is None:
                raise ValueError("账本没有原貌衣服")
            remain = int(self.daily.get("remain") or 0)
            if remain <= 0:
                raise ValueError(NO_TRIES)
            self.daily["remain"] = remain - 1
            self.add_have(base.id, drop_count)
            return JOB_FARM
        if job in {JOB_EVO_HUA, "evo_hua"}:
            return self._evolve("base", "hua")
        if job in {JOB_EVO_RARE, "evo_rare"}:
            return self._evolve("hua", "rare")
        raise ValueError(f"未知回调: {job}")

    def _evolve(self, from_tier: str, to_tier: str) -> str:
        source = self.piece_by_tier(from_tier)
        target = self.piece_by_tier(to_tier)
        if source is None or target is None:
            raise ValueError("进化链不完整")
        need = self.evo_need(target)
        if source.consumable < need:
            raise ValueError(f"{source.name} 可用件数不足 {need}")
        source.have = max(source.keep, source.have - need)
        target.have += 1
        self.save()
        return target.source.job or to_tier

    def gain(self, item_id: str, count: int = 1) -> ClothingItem:
        self.add_have(item_id, count)
        item = self.get(item_id)
        if item is None:
            raise ValueError("找不到衣服记录")
        return item

    def stage_limit(self, stage: str) -> int:
        if stage and stage == self.daily.get("stage"):
            return int(self.daily.get("limit") or 3)
        return 3

    def used_today(self, stage: str) -> int:
        self.ensure_today()
        if stage != self.daily.get("stage"):
            return 0
        return max(0, int(self.daily.get("limit") or 3) - int(self.daily.get("remain") or 0))

    def remaining(self, stage: str, daily_limit: int | None = None) -> int:
        self.ensure_today()
        if not stage or stage != self.daily.get("stage"):
            return 0
        return max(0, int(self.daily.get("remain") or 0))

    def record_clear(self, stage: str) -> int:
        stage = stage.strip()
        if not stage:
            raise ValueError("请先填写关卡")
        self.ensure_today()
        if stage != self.daily.get("stage"):
            self.daily["stage"] = stage
        remain = int(self.daily.get("remain") or 0)
        if remain <= 0:
            raise ValueError(NO_TRIES)
        self.daily["remain"] = remain - 1
        self.save()
        return int(self.daily.get("remain") or 0)

    def farm_queue(self) -> list[tuple[ClothingItem, int, int]]:
        if self.next_job() != JOB_FARM:
            return []
        base = self.get(self.piece_by_tier("base").id) if self.piece_by_tier("base") else None
        if base is None or not base.stage:
            return []
        return [(base, max(0, base.needed - base.owned), self.remaining(base.stage))]

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
        tier = "base"
        for key, label in TIER_LABELS.items():
            if category == label or category == key:
                tier = key
        source = ItemSource(type="stage", stage=stage.strip(), daily_limit=daily_limit)
        if stage.strip() == "":
            source = ItemSource(type="evolve", need=needed, job="")
        piece = ChainPiece(
            id=uuid4().hex,
            name=name.strip(),
            tier=tier,
            keep=max(0, needed - owned) if owned > needed else 0,
            have=owned,
            source=source,
        )
        if parent_id:
            index = next((i for i, item in enumerate(self.chain) if item.id == parent_id), -1)
            if index < 0:
                raise ValueError("找不到上级衣服")
            self.chain.insert(index + 1, piece)
        else:
            self.chain.append(piece)
        self.save()
        item = self.get(piece.id)
        if item is None:
            raise ValueError("保存后无法读取衣服")
        return item

    def upsert(self, item: ClothingItem) -> ClothingItem:
        piece = self.piece(item.id)
        if piece is None:
            return self.add_item(
                item.name,
                item.category,
                item.needed,
                item.owned,
                item.stage,
                item.daily_limit,
                item.parent_id,
            )
        piece.name = item.name.strip()
        piece.have = item.owned
        if piece.source.type == "stage":
            piece.source.stage = item.stage.strip()
            piece.keep = item.needed
        else:
            piece.source.need = item.needed
        self.save()
        updated = self.get(item.id)
        if updated is None:
            raise ValueError("找不到衣服记录")
        return updated

    def remove(self, item_id: str) -> None:
        self.chain = [item for item in self.chain if item.id != item_id]
        if self.target.get("id") == item_id:
            self.target = {"id": "", "name": "", "asset": ""}
        self.save()
