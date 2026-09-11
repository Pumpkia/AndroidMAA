"""奇迹暖暖关卡编号：少女/公主、章节、支线。"""

from __future__ import annotations

from dataclasses import dataclass
import re


_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
_CHAPTER_RE = re.compile(
    r"第\s*([一二三四五六七八九十百零\d]+)\s*章\s*([上下])?"
)
_STAGE_RE = re.compile(
    r"卷\s*([IVXivx一二三四五]+)\s*(\d+)\s*[-－]\s*(支)?\s*(\d+)"
)
_SHORT_RE = re.compile(
    r"^(少女|公主)?\s*(\d+)\s*([上下])?\s*[-－]\s*(支)?\s*(\d+)$"
)
_REMAINING_RE = re.compile(r"今日剩余次数\s*[：:]\s*(\d+)\s*/\s*(\d+)")


def parse_chinese_int(text: str) -> int:
    value = (text or "").strip()
    if not value:
        raise ValueError("空数字")
    if value.isdigit():
        return int(value)
    if value in _DIGITS:
        return _DIGITS[value]
    if value.startswith("十"):
        rest = value[1:]
        return 10 + (parse_chinese_int(rest) if rest else 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return parse_chinese_int(left) * 10 + (parse_chinese_int(right) if right else 0)
    raise ValueError(f"无法解析数字: {text}")


def to_chinese_int(value: int) -> str:
    if value < 0:
        raise ValueError("章节号不能为负")
    names = "零一二三四五六七八九十"
    if value <= 10:
        return names[value]
    if value < 20:
        return "十" + (names[value - 10] if value > 10 else "")
    tens, ones = divmod(value, 10)
    return names[tens] + "十" + (names[ones] if ones else "")


def parse_volume(text: str) -> int:
    value = (text or "").strip()
    if value.isdigit():
        return int(value)
    if value in _ROMAN:
        return _ROMAN[value]
    if value in _DIGITS:
        return _DIGITS[value]
    raise ValueError(f"无法解析卷: {text}")


def volume_roman(value: int) -> str:
    return {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(value, str(value))


@dataclass(frozen=True)
class StageRef:
    difficulty: str
    chapter: int
    stage: int
    branch: bool = False
    chapter_part: str = ""
    volume: int = 1

    def __post_init__(self) -> None:
        if self.difficulty not in {"少女", "公主"}:
            raise ValueError("难度只支持少女或公主")
        if self.chapter < 1 or self.stage < 1:
            raise ValueError("章节和关卡必须是正整数")
        if self.chapter_part not in {"", "上", "下"}:
            raise ValueError("章节分段只支持上或下")
        if self.volume < 1:
            raise ValueError("卷号必须是正整数")

    @property
    def chapter_label(self) -> str:
        return f"第{to_chinese_int(self.chapter)}章{self.chapter_part}"

    @property
    def stage_label(self) -> str:
        branch = "支" if self.branch else ""
        return f"卷 {volume_roman(self.volume)} {self.chapter}-{branch}{self.stage}"

    @property
    def canonical(self) -> str:
        branch = "支" if self.branch else ""
        return f"{self.difficulty}{self.chapter}{self.chapter_part}-{branch}{self.stage}"


def parse_stage(value: str, default_difficulty: str = "少女") -> StageRef:
    text = re.sub(r"\s+", "", value or "")
    if not text:
        raise ValueError("关卡不能为空")
    difficulty = default_difficulty
    if text.startswith("公主"):
        difficulty = "公主"
        text = text[2:]
    elif text.startswith("少女"):
        difficulty = "少女"
        text = text[2:]
    volume = 1
    volume_match = re.match(r"卷([IVXivx一二三四五]+)", text)
    if volume_match:
        volume = parse_volume(volume_match.group(1))
        text = text[volume_match.end():]
    stage_match = _STAGE_RE.search(value or "")
    if stage_match and "章" not in text:
        return StageRef(
            difficulty=difficulty,
            volume=parse_volume(stage_match.group(1)),
            chapter=int(stage_match.group(2)),
            branch=bool(stage_match.group(3)),
            stage=int(stage_match.group(4)),
        )
    short = _SHORT_RE.match(f"{difficulty}{text}" if not text.startswith(("少女", "公主")) else text)
    if short is None:
        short = _SHORT_RE.match(text)
    if short:
        return StageRef(
            difficulty=short.group(1) or difficulty,
            chapter=int(short.group(2)),
            chapter_part=short.group(3) or "",
            branch=bool(short.group(4)),
            stage=int(short.group(5)),
            volume=volume,
        )
    compact = re.fullmatch(r"(\d+)([上下])?[-－](支)?(\d+)", text)
    if compact:
        return StageRef(
            difficulty=difficulty,
            chapter=int(compact.group(1)),
            chapter_part=compact.group(2) or "",
            branch=bool(compact.group(3)),
            stage=int(compact.group(4)),
            volume=volume,
        )
    raise ValueError(f"无法识别关卡: {value}")


def parse_chapter_label(value: str) -> tuple[int, str] | None:
    match = _CHAPTER_RE.search(value or "")
    if not match:
        return None
    try:
        return parse_chinese_int(match.group(1)), match.group(2) or ""
    except ValueError:
        return None


def parse_stage_label(value: str) -> tuple[int, int, bool, int] | None:
    match = _STAGE_RE.search(value or "")
    if not match:
        return None
    try:
        return (
            parse_volume(match.group(1)),
            int(match.group(2)),
            bool(match.group(3)),
            int(match.group(4)),
        )
    except ValueError:
        return None


def parse_remaining(value: str) -> tuple[int, int] | None:
    match = _REMAINING_RE.search(value or "")
    if not match:
        return None
    remaining = int(match.group(1))
    limit = int(match.group(2))
    if limit < 1 or remaining < 0 or remaining > limit:
        return None
    return remaining, limit
