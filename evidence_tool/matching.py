"""候选配对的可比性核对与配对级净节省。

业务人员在 ``matched_groups.json`` 提出的配对只是候选，不作确定匹配
结论。本模块逐对核对：

* 是否恰为一程传统、一程送车，且两程的记录都联合可行；
* 出行日、交车窗、往返距离、归还方式等维度能否公平对应，不能对应的
  差异保留为覆盖说明，而不是静默丢弃；
* 净节省只在相同旅程权重下比较，按可证实区间输出，绝不各取最有利的
  一列拼出“省了时间”。

未结束的经历（缺“可离开”）不能由最后一条上报封口：其去程区间仍然
可证实，但回程及全程结论标记为开放，不能进入返程类证据集。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .engine import JourneyFeasibility
from .records import (
    DELIVERY,
    TRADITIONAL,
    EvidenceBundle,
)

# 需要在两程之间公平对应的旅程维度；任一不一致都进入覆盖说明。
COMPARE_DIMENSIONS = (
    "day",
    "window",
    "distance",
    "return_kind",
    "pickup",
    "area",
    "party",
    "version",
)

# 文案证据默认按这些维度描述适用边界（version/area 同时由文案过滤）。
COVERAGE_DIMENSIONS = (
    "window",
    "pickup",
    "return_kind",
    "distance",
)


@dataclass
class PairEvidence:
    """一对候选对照在截止日资料下的证据。"""

    pair: str
    weight: float
    basis: str
    traditional: Optional[str]
    delivery: Optional[str]
    eligible: bool
    exclusion_reasons: list[str] = field(default_factory=list)
    coverage_mismatches: dict[str, tuple[object, object]] = field(default_factory=dict)
    #: 去程净节省区间（传统用时 − 送车用时），分钟
    pickup_saving: Optional[tuple[float, float]] = None
    #: 回程净节省区间，分钟
    return_saving: Optional[tuple[float, float]] = None
    #: 全程净节省区间，分钟；任一程开放则为 None
    total_saving: Optional[tuple[float, float]] = None
    #: 送车一程是否仍未结束（不能封口）
    open_ended: bool = False
    traditional_feasibility: Optional[JourneyFeasibility] = None
    delivery_feasibility: Optional[JourneyFeasibility] = None

    def segment_saving(self, segment: str) -> Optional[tuple[float, float]]:
        return getattr(self, f"{segment}_saving")


def _interval_minus(
    a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """区间相减 ``a - b`` 的紧上下界。"""
    return (a[0] - b[1], a[1] - b[0])


def _saving_interval(
    traditional: JourneyFeasibility,
    delivery: JourneyFeasibility,
    segment: str,
) -> Optional[tuple[float, float]]:
    a = getattr(traditional, f"{segment}_span")
    b = getattr(delivery, f"{segment}_span")
    if a is None or b is None:
        return None
    return _interval_minus(a, b)


def build_pair_evidence(
    bundle: EvidenceBundle,
    feasibility: dict[str, JourneyFeasibility],
) -> list[PairEvidence]:
    """把候选配对表转换成带可比性说明与净节省区间的证据列表。"""
    grouped: dict[str, list[dict]] = {}
    for row in bundle.matched_groups:
        grouped.setdefault(row["pair"], []).append(row)

    evidence: list[PairEvidence] = []
    for pair_id in sorted(grouped):
        members = grouped[pair_id]
        weight = float(members[0]["weight"])
        basis = members[0]["basis"]
        services = {
            bundle.journey(m["journey"])["service"]: m["journey"] for m in members
        }
        traditional = services.get(TRADITIONAL)
        delivery = services.get(DELIVERY)

        item = PairEvidence(
            pair=pair_id,
            weight=weight,
            basis=basis,
            traditional=traditional,
            delivery=delivery,
            eligible=False,
        )

        if len(members) != 2 or traditional is None or delivery is None:
            item.exclusion_reasons.append(
                "候选配对不构成一程传统、一程送车的完整对照"
            )
            evidence.append(item)
            continue

        f_trad = feasibility[traditional]
        f_del = feasibility[delivery]
        item.traditional_feasibility = f_trad
        item.delivery_feasibility = f_del
        item.open_ended = f_del.open_ended

        j_trad = bundle.journey(traditional)
        j_del = bundle.journey(delivery)
        for dim in COMPARE_DIMENSIONS:
            if j_trad[dim] != j_del[dim]:
                item.coverage_mismatches[dim] = (j_trad[dim], j_del[dim])

        if not f_trad.feasible or not f_del.feasible:
            item.exclusion_reasons.append("配对中存在联合不可行的旅程记录")
        if f_del.open_ended:
            item.exclusion_reasons.append(
                "送车经历尚未结束（缺可离开节点），回程与全程不能由最后上报封口"
            )

        item.pickup_saving = _saving_interval(f_trad, f_del, "pickup")
        item.return_saving = _saving_interval(f_trad, f_del, "return")
        item.total_saving = _saving_interval(f_trad, f_del, "total")
        if item.total_saving is None and (
            item.pickup_saving is not None and item.return_saving is not None
        ):
            # 兜底：模型未给全程区间时才退回分段相加（通常更松）
            item.total_saving = (
                item.pickup_saving[0] + item.return_saving[0],
                item.pickup_saving[1] + item.return_saving[1],
            )

        # 去程证据在两程可行且去程节点齐全时即可用；
        # 全程/回程证据另外要求送车一程已经结束。
        item.eligible = (
            f_trad.feasible
            and f_del.feasible
            and item.pickup_saving is not None
        )
        evidence.append(item)

    return evidence


def interval_guarantees(interval: tuple[float, float], threshold: float) -> bool:
    """可证实下界是否达到门槛（对匹配误差稳健的通过判据）。"""
    return interval[0] >= threshold


def interval_allows(interval: tuple[float, float], threshold: float) -> bool:
    """区间上界是否仍可能达到门槛（不确定性下的乐观判据）。"""
    return interval[1] >= threshold


def coverage_key(journey: dict, dimensions=COVERAGE_DIMENSIONS) -> tuple:
    """旅程在给定覆盖维度上的取值组合，用于细分边界描述。"""
    return tuple(journey[d] for d in dimensions)


def describe_coverage(values: dict) -> str:
    """把覆盖维度取值格式化成人类可读的说明。"""
    return "；".join(f"{k}={v}" for k, v in values.items())
