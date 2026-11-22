"""资料装载与截止日（as-of）修订选择。

业务原始记录允许保留冲突、未决关系和尚未到达的观察。工具不修改原始
JSON，只在给定截止日 ``as_of`` 下选择当时可见的最高修订；截止日之后
才出现的修订不参与评估，从而可以复放“收到更正前/后”的结论变化。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

TABLES = (
    "journeys",
    "matched_groups",
    "timestamps",
    "calibrations",
    "statements",
    "pages",
    "connections",
)

# 旅客可用节点的固定业务顺序：到交车点 → 可启程 → 结束游览 → 可离开。
EVENT_ORDER = ("到交车点", "可启程", "结束游览", "可离开")
ARRIVAL = "到交车点"
DEPARTURE = "可启程"
TOUR_END = "结束游览"
FREE_TO_LEAVE = "可离开"

TRADITIONAL = "传统"
DELIVERY = "送车"

SAVINGS_CLAIM = "典型时间节省"
BUFFER_CLAIM = "最短返程缓冲"


def load_table(data_dir: str | Path, name: str) -> list[dict[str, Any]]:
    path = Path(data_dir) / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def latest_visible(
    rows: Iterable[dict[str, Any]],
    key_fields: tuple[str, ...],
    as_of: str,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    """按业务键保留截止日可见的最高修订。

    ``visible_day > as_of`` 的行视为当时尚不可见；同一业务键下取
    ``revision`` 最大的一行。返回字典而不是静默覆盖，调用方可以核对
    被替换掉的旧修订。
    """
    chosen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if row["visible_day"] > as_of:
            continue
        key = tuple(row[f] for f in key_fields)
        old = chosen.get(key)
        if old is None or row["revision"] > old["revision"]:
            chosen[key] = row
    return chosen


@dataclass(frozen=True)
class EventObservation:
    """截止日下一个事件的唯一有效记录（设备钟面分钟上下界）。"""

    event: str
    journey: str
    kind: str
    device: str
    clock_lo: float
    clock_hi: float
    visible_day: str
    revision: int


@dataclass(frozen=True)
class Calibration:
    """同一设备同一日公用的未知钟差区间（真实分钟 = 设备分钟 + 钟差）。"""

    day: str
    device: str
    offset_lo: float
    offset_hi: float
    visible_day: str
    revision: int


@dataclass
class EvidenceBundle:
    """一次评估所使用的完整资料快照。"""

    as_of: str
    data_dir: Path
    journeys: list[dict[str, Any]]
    matched_groups: list[dict[str, Any]]
    statements: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    connections: list[dict[str, Any]]
    events: dict[tuple[str, str], EventObservation]
    calibrations: dict[tuple[str, str], Calibration]
    suppressed_rows: dict[str, int]

    def journey(self, journey_id: str) -> dict[str, Any]:
        return self._journey_index[journey_id]

    def __post_init__(self) -> None:
        self._journey_index = {row["journey"]: row for row in self.journeys}

    def events_of(self, journey_id: str) -> dict[str, EventObservation]:
        return {
            kind: obs
            for (jid, kind), obs in self.events.items()
            if jid == journey_id
        }

    def calibration_for(self, day: str, device: str) -> Calibration | None:
        return self.calibrations.get((day, device))


def load_bundle(data_dir: str | Path, as_of: str = "9999-12-31") -> EvidenceBundle:
    """装载资料并按截止日收敛事件与校准修订。

    非时序表（journeys 等）整体装载；时序表按业务键保留最高可见修订，
    被截止日挡掉的行数记录在 ``suppressed_rows`` 中，供覆盖说明引用。
    """
    data_dir = Path(data_dir)
    raw = {name: load_table(data_dir, name) for name in TABLES}

    event_rows = latest_visible(raw["timestamps"], ("event",), as_of)
    cal_rows = latest_visible(
        raw["calibrations"], ("day", "device"), as_of
    )

    events = {
        (row["journey"], row["kind"]): EventObservation(
            event=row["event"],
            journey=row["journey"],
            kind=row["kind"],
            device=row["device"],
            clock_lo=float(row["clock_min_lo"]),
            clock_hi=float(row["clock_min_hi"]),
            visible_day=row["visible_day"],
            revision=int(row["revision"]),
        )
        for row in event_rows.values()
    }
    calibrations = {
        (row["day"], row["device"]): Calibration(
            day=row["day"],
            device=row["device"],
            offset_lo=float(row["offset_lo"]),
            offset_hi=float(row["offset_hi"]),
            visible_day=row["visible_day"],
            revision=int(row["revision"]),
        )
        for row in cal_rows.values()
    }

    suppressed = {
        "timestamps": sum(
            1 for row in raw["timestamps"] if row["visible_day"] > as_of
        ),
        "calibrations": sum(
            1 for row in raw["calibrations"] if row["visible_day"] > as_of
        ),
    }

    return EvidenceBundle(
        as_of=as_of,
        data_dir=data_dir,
        journeys=raw["journeys"],
        matched_groups=raw["matched_groups"],
        statements=raw["statements"],
        pages=raw["pages"],
        connections=raw["connections"],
        events=events,
        calibrations=calibrations,
        suppressed_rows=suppressed,
    )
