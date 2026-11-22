"""两类宣传文案的证据评估。

* ``典型时间节省``：声称典型旅客能省某个时长。必须能看到同样旅程
  权重下的净节省分布，以及它对匹配误差（保守/名义/乐观）、缺观察
  （删失归队边界）和抽样（Wilson + 自助）的敏感性。
* ``最短返程缓冲``：声称某种返程安排有稳定缓冲。关心迟尾，去程和
  回程必须从记录约束一致的同一组可行行程里联合评估，不能拼接分别
  最稳的半程；返程推广只面向去程在 10 时前能启程的行程，该条件与
  缓冲用同一份有效时间资料判断。

能通过的细分不能被悄悄推广到总体：每个结论都带明确的覆盖说明
（窗口、点位、行程版本等），文案缩小覆盖后也不能继续投到原群体。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .engine import JourneyFeasibility
from .matching import (
    COVERAGE_DIMENSIONS,
    PairEvidence,
    coverage_key,
)
from .records import (
    BUFFER_CLAIM,
    DELIVERY,
    SAVINGS_CLAIM,
    EvidenceBundle,
)
from .sensitivity import (
    missing_observation_bounds,
    weighted_bootstrap,
    weighted_share,
    wilson_interval,
)

# 返程推广仅面向去程在 10 时（600 分钟）前能启程的行程。
OUTBOUND_DEPARTURE_LIMIT = 600.0


@dataclass
class SavingsResult:
    """“典型时间节省”文案的证据结论。"""

    statement: str
    passed: bool
    threshold_minutes: float
    reliability: float
    confidence: float
    segment: str
    eligible_pairs: list[str] = field(default_factory=list)
    excluded_pairs: dict[str, list[str]] = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    distribution: list[dict] = field(default_factory=list)
    estimates: dict = field(default_factory=dict)
    missing_bounds: Optional[dict] = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class BufferResult:
    """“最短返程缓冲”文案的证据结论（迟尾导向）。"""

    statement: str
    passed: bool
    buffer_minutes: float
    reliability: float
    confidence: float
    eligible_journeys: list[str] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    tail: dict = field(default_factory=dict)
    share_estimate: Optional[dict] = None
    reasons: list[str] = field(default_factory=list)


def _statement_targets(statement: dict) -> tuple[str, Optional[set[str]]]:
    """解析文案的产品版本与地区定向（“双区”展开为两个具体地区）。"""
    area = statement["area"]
    if area == "双区":
        areas = {"西湾", "东岸"}
    else:
        areas = {area}
    return statement["version"], areas


def _pair_matches_target(
    bundle: EvidenceBundle, pair: PairEvidence, version: str, areas: set[str]
) -> bool:
    if pair.delivery is None or pair.traditional is None:
        return False
    delivery = bundle.journey(pair.delivery)
    return delivery["version"] == version and delivery["area"] in areas


def _pair_matches_scenario(
    bundle: EvidenceBundle,
    pair: PairEvidence,
    scenario_filters: dict,
) -> bool:
    """场景过滤：两程都必须满足给定维度，保证对比仍在同条件内。"""
    if not scenario_filters or pair.delivery is None or pair.traditional is None:
        return True
    for dim, wanted in scenario_filters.items():
        if bundle.journey(pair.delivery).get(dim) != wanted:
            return False
        if bundle.journey(pair.traditional).get(dim) != wanted:
            return False
    return True


def evaluate_savings_statement(
    bundle: EvidenceBundle,
    pairs: list[PairEvidence],
    statement: dict,
    *,
    segment: str | None = None,
    scenario_filters: dict | None = None,
    replicates: int = 10000,
    seed: int | None = 71235,
) -> SavingsResult:
    """评估典型节省文案。

    ``segment`` 取 ``total``（全程，默认）、``pickup``（仅去程）或
    ``return``（仅回程）。门槛判定全部基于配对净节省的可证实区间。
    ``scenario_filters`` 按旅程维度（如 pickup/window/return_kind）
    进一步收窄旅客场景；收窄后的结论不能投回未收窄的群体。
    """
    assert statement["claim"] == SAVINGS_CLAIM
    segment = segment or statement.get("segment", "total")
    if segment not in ("total", "pickup", "return"):
        raise ValueError(f"不支持的用时口径：{segment}")
    scenario_filters = scenario_filters or statement.get(
        "scenario_filters", {}
    )
    version, areas = _statement_targets(statement)
    threshold = float(statement["minutes"])
    reliability = float(statement["reliability"])
    confidence = float(statement["confidence"])

    result = SavingsResult(
        statement=statement["statement"],
        passed=False,
        threshold_minutes=threshold,
        reliability=reliability,
        confidence=confidence,
        segment=segment,
    )

    targeted = [
        p
        for p in pairs
        if _pair_matches_target(bundle, p, version, areas)
        and _pair_matches_scenario(bundle, p, scenario_filters)
    ]
    result.excluded_pairs["不在文案版本/地区/场景定向内"] = [
        p.pair for p in pairs if p not in targeted
    ]

    complete: list[PairEvidence] = []
    missing: list[PairEvidence] = []
    for p in targeted:
        interval = p.segment_saving(segment)
        segment_open = p.open_ended and segment != "pickup"
        if not p.eligible or interval is None or segment_open:
            missing.append(p)
        else:
            complete.append(p)
    result.excluded_pairs["缺观察/未结束/不可行，不能作正证"] = [
        p.pair for p in missing
    ]

    if not complete:
        result.reasons.append("定向范围内没有可作正证的完整配对")
        return result

    # 净节省分布：每对给出可证实区间与中点，并标注能否保证达到门槛
    distribution = []
    for p in complete:
        lo, hi = p.segment_saving(segment)
        distribution.append(
            {
                "pair": p.pair,
                "weight": p.weight,
                "saving_lo": lo,
                "saving_hi": hi,
                "saving_mid": (lo + hi) / 2,
                "guaranteed": lo >= threshold,
                "ruled_out": hi < threshold,
                "coverage": dict(zip(COVERAGE_DIMENSIONS, coverage_key(
                    bundle.journey(p.delivery)
                ))),
                "coverage_mismatches": dict(p.coverage_mismatches),
            }
        )
    result.distribution = distribution

    def conservative(p: PairEvidence) -> bool:
        iv = p.segment_saving(segment)
        return iv is not None and iv[0] >= threshold

    def nominal(p: PairEvidence) -> bool:
        iv = p.segment_saving(segment)
        return iv is not None and (iv[0] + iv[1]) / 2 >= threshold

    def optimistic(p: PairEvidence) -> bool:
        iv = p.segment_saving(segment)
        return iv is not None and iv[1] >= threshold

    estimates = {}
    for label, predicate in (
        ("conservative", conservative),
        ("nominal", nominal),
        ("optimistic", optimistic),
    ):
        est = weighted_share(complete, predicate, confidence, label)
        bs_lo, bs_hi = weighted_bootstrap(
            complete, predicate, confidence, replicates, seed
        )
        est.bootstrap_low, est.bootstrap_high = bs_lo, bs_hi
        estimates[label] = est.as_dict()
    result.estimates = estimates

    bounds = missing_observation_bounds(complete, missing, nominal)
    result.missing_bounds = bounds.as_dict()

    # 覆盖说明：实际支持到哪些窗口、点位、归还方式、距离、版本
    coverage_values: dict[str, set] = {dim: set() for dim in COVERAGE_DIMENSIONS}
    coverage_values["version"] = set()
    coverage_values["area"] = set()
    mismatch_dims: dict[str, int] = {}
    for p in complete:
        j = bundle.journey(p.delivery)
        for dim in COVERAGE_DIMENSIONS:
            coverage_values[dim].add(j[dim])
        coverage_values["version"].add(j["version"])
        coverage_values["area"].add(j["area"])
        for dim in p.coverage_mismatches:
            mismatch_dims[dim] = mismatch_dims.get(dim, 0) + 1
    result.coverage = {
        "supported": {k: sorted(v) for k, v in coverage_values.items()},
        "pairwise_mismatch_dimensions": mismatch_dims,
        "shift_window_pairs": sorted(
            p.pair for p in complete if p.basis != "班窗相同"
        ),
        "open_or_missing_pairs": [p.pair for p in missing],
        "scenario_filters": dict(scenario_filters),
    }

    # 通过判据：对匹配误差稳健（保守口径）且抽样置信下界仍达 reliability
    decision_est = estimates["conservative"]
    decision = (
        decision_est["wilson_low"] >= reliability
        and decision_est["bootstrap_low"] >= reliability
    )
    result.eligible_pairs = [p.pair for p in complete]
    if decision:
        result.passed = True
    else:
        result.reasons.append(
            "保守口径（净节省区间下界达到门槛）的加权份额置信下界 "
            f"{decision_est['wilson_low']:.3f} 未达到可靠性要求 {reliability:.2f}"
        )
    return result


def evaluate_buffer_statement(
    bundle: EvidenceBundle,
    feasibility: dict[str, JourneyFeasibility],
    statement: dict,
    pairs: list[PairEvidence] | None = None,
) -> BufferResult:
    """评估最短返程缓冲文案。

    缓冲 = 表列接驳发车 − 旅客可离开的真实时刻。去程、回程在同一个
    送车旅程上联合判定：去程“可启程”必须在 10 时前（用可证实上界），
    回程缓冲必须在全部联合可行赋值下都达到门槛（用可证实下界，即
    迟尾口径）。任一环节缺观察则该行程不进入证据集。

    可靠性份额按配对权重加权（与节省类文案同一权重口径）；未提供
    配对表时退回等权旅程口径，并在结果中注明。
    """
    assert statement["claim"] == BUFFER_CLAIM
    version, areas = _statement_targets(statement)
    buffer_minutes = float(statement["minutes"])
    reliability = float(statement["reliability"])
    confidence = float(statement["confidence"])

    result = BufferResult(
        statement=statement["statement"],
        passed=False,
        buffer_minutes=buffer_minutes,
        reliability=reliability,
        confidence=confidence,
    )

    connections = {
        (c["area"], c["window"]): float(c["departure"])
        for c in bundle.connections
    }

    # 送车旅程 -> 所属配对权重（同一旅程至多属于一个候选配对）
    pair_weight: dict[str, float] = {}
    if pairs:
        for p in pairs:
            if p.delivery is not None:
                pair_weight[p.delivery] = p.weight

    eligible: list[str] = []
    buffers: list[float] = []
    eligible_weight = 0.0
    denominator_weight = 0.0
    excluded: dict[str, list[str]] = {
        "非送车服务": [],
        "版本或地区不匹配": [],
        "记录不可行": [],
        "经历未结束或缺节点": [],
        "去程无法保证10时前启程": [],
        "接驳发车缺失": [],
    }

    for journey in bundle.journeys:
        jid = journey["journey"]
        if journey["service"] != DELIVERY:
            excluded["非送车服务"].append(jid)
            continue
        if journey["version"] != version or journey["area"] not in areas:
            excluded["版本或地区不匹配"].append(jid)
            continue
        f = feasibility[jid]
        if not f.feasible:
            excluded["记录不可行"].append(jid)
            continue
        if f.open_ended or f.return_span is None or f.pickup_span is None:
            excluded["经历未结束或缺节点"].append(jid)
            continue

        # 分母：定向内、记录完整且联合可行的送车行程（开放行程已排除）
        weight = pair_weight.get(jid, 1.0 if pairs is None else 0.0)
        if pairs is not None and jid not in pair_weight:
            # 未进入任何候选配对的行程不能借用配对权重口径
            excluded.setdefault("未进入候选配对，不计入加权份额", []).append(jid)
            continue
        denominator_weight += weight

        # 去程条件：可启程真实时刻的可证实上界 <= 10:00
        depart_bounds = f.true_time_bounds.get("可启程")
        if depart_bounds is None or depart_bounds[1] > OUTBOUND_DEPARTURE_LIMIT:
            excluded["去程无法保证10时前启程"].append(jid)
            continue

        departure = connections.get((journey["area"], journey["window"]))
        if departure is None:
            excluded["接驳发车缺失"].append(jid)
            continue

        leave_bounds = f.true_time_bounds["可离开"]
        # 迟尾口径：最小可能缓冲 = 最晚可离开 → 最早缓冲
        min_buffer = departure - leave_bounds[1]
        if min_buffer >= buffer_minutes:
            eligible.append(jid)
            buffers.append(min_buffer)
            eligible_weight += weight

    result.excluded = {k: v for k, v in excluded.items() if v}
    result.eligible_journeys = eligible

    if denominator_weight <= 0:
        result.reasons.append("定向内没有可进入加权份额口径的完整送车行程")
        return result
    if not eligible:
        result.reasons.append("没有同时满足去程时点与回程缓冲的联合可行行程")
        return result

    low, high = wilson_interval(eligible_weight, denominator_weight, confidence)
    result.share_estimate = {
        "weighting": "配对权重" if pairs is not None else "旅程等权",
        "passed_journeys": len(eligible),
        "passed_weight": round(eligible_weight, 6),
        "denominator_weight": round(denominator_weight, 6),
        "share": round(eligible_weight / denominator_weight, 6),
        "wilson_low": round(low, 6),
        "wilson_high": round(high, 6),
    }

    ordered = sorted(buffers)

    def percentile(sorted_values: list[float], q: float) -> float:
        """最近秩百分位（含端点），用于迟尾刻画。"""
        if not sorted_values:
            return math.nan
        rank = max(1, math.ceil(q * len(sorted_values)))
        return sorted_values[min(len(sorted_values), rank) - 1]

    result.tail = {
        "worst_min_buffer": ordered[0],
        "p10_min_buffer": percentile(ordered, 0.10),
        "median_min_buffer": percentile(ordered, 0.50),
        "all_min_buffers": [round(x, 3) for x in ordered],
    }

    coverage_values: dict[str, set] = {dim: set() for dim in COVERAGE_DIMENSIONS}
    coverage_values["version"] = set()
    coverage_values["area"] = set()
    for jid in eligible:
        j = bundle.journey(jid)
        for dim in COVERAGE_DIMENSIONS:
            coverage_values[dim].add(j[dim])
        coverage_values["version"].add(j["version"])
        coverage_values["area"].add(j["area"])
    result.coverage = {"supported": {k: sorted(v) for k, v in coverage_values.items()}}

    if low >= reliability:
        result.passed = True
    else:
        result.reasons.append(
            f"联合可行行程中保证缓冲达标的份额置信下界 {low:.3f} "
            f"低于可靠性要求 {reliability:.2f}"
        )
    return result
