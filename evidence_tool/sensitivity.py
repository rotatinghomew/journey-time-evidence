"""净节省分布对匹配误差、缺观察与抽样的敏感性。

三类敏感性彼此独立、全部可复算：

1. **匹配误差（区间不确定性）**：每个配对的净节省是一个可证实区间，
   同一份资料下给出三种判据——保守（区间下界达到门槛）、名义（区间
   中点达到门槛）、乐观（区间上界达到门槛）。三者差距即钟差与钟面
   不确定性对结论的影响。
2. **缺观察**：未结束、缺节点或不可行的配对没有正证资格。分别计算
   “仅完整配对”的份额，以及把缺观察按不利（未达门槛）/有利（达到
   门槛）归队后的边界，展示删失会把结论推向哪里。
3. **抽样**：用配对权重做加权自助（weighted bootstrap），输出份额
   分布与给定置信水平下的分位数；同时给出加权 Wilson 区间作为不需要
   模拟的解析对照。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Sequence

from .matching import PairEvidence

Predicate = Callable[[PairEvidence], bool]


@dataclass
class ShareEstimate:
    """一个通过份额的点估计与不确定性刻画。"""

    label: str
    passed_weight: float
    total_weight: float
    share: float
    wilson_low: float
    wilson_high: float
    bootstrap_low: float | None = None
    bootstrap_high: float | None = None
    included_pairs: int = 0
    excluded_open: int = 0

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "passed_weight": round(self.passed_weight, 6),
            "total_weight": round(self.total_weight, 6),
            "share": round(self.share, 6),
            "wilson_low": round(self.wilson_low, 6),
            "wilson_high": round(self.wilson_high, 6),
            "bootstrap_low": (
                None if self.bootstrap_low is None else round(self.bootstrap_low, 6)
            ),
            "bootstrap_high": (
                None if self.bootstrap_high is None else round(self.bootstrap_high, 6)
            ),
            "included_pairs": self.included_pairs,
            "excluded_open": self.excluded_open,
        }


def wilson_interval(successes: float, trials: float, confidence: float) -> tuple[float, float]:
    """加权（分数计数）Wilson 区间。

    权重被视为重复次数的分数，分母为总权重；解析区间不依赖随机种子，
    与自助结果互为对照。
    """
    if trials <= 0:
        return (math.nan, math.nan)
    # 双侧正态分位
    z = _normal_quantile(1 - (1 - confidence) / 2)
    phat = successes / trials
    denom = 1 + z * z / trials
    center = (phat + z * z / (2 * trials)) / denom
    half = (
        z
        * math.sqrt((phat * (1 - phat) + z * z / (4 * trials)) / trials)
        / denom
    )
    return (max(0.0, center - half), min(1.0, center + half))


def _normal_quantile(p: float) -> float:
    """标准正态分位数（Acklam 算法），避免额外依赖。"""
    if not 0 < p < 1:
        raise ValueError("分位概率必须在 (0,1) 内")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def weighted_share(
    pairs: Sequence[PairEvidence],
    predicate: Predicate,
    confidence: float,
    label: str,
) -> ShareEstimate:
    """在给定配对集合上计算加权通过份额与 Wilson 区间。"""
    total = sum(p.weight for p in pairs)
    passed = sum(p.weight for p in pairs if predicate(p))
    open_count = sum(1 for p in pairs if p.open_ended)
    low, high = wilson_interval(passed, total, confidence)
    return ShareEstimate(
        label=label,
        passed_weight=passed,
        total_weight=total,
        share=(passed / total if total else math.nan),
        wilson_low=low,
        wilson_high=high,
        included_pairs=len(pairs),
        excluded_open=open_count,
    )


def weighted_bootstrap(
    pairs: Sequence[PairEvidence],
    predicate: Predicate,
    confidence: float,
    replicates: int = 10000,
    seed: int | None = 71235,
) -> tuple[float, float]:
    """对配对做有放回重采样的加权自助分位区间。

    每次重采样抽取与原样本同量的配对，按其权重计算通过份额；取经验
    分布的双侧分位。固定种子保证复核可重现。
    """
    if not pairs:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    n = len(pairs)
    draws: list[float] = []
    weights = [p.weight for p in pairs]
    for _ in range(replicates):
        tw = tp = 0.0
        for _ in range(n):
            p = pairs[rng.randrange(n)]
            tw += p.weight
            if predicate(p):
                tp += p.weight
        draws.append(tp / tw if tw else 0.0)
    draws.sort()
    alpha = 1 - confidence
    lo = draws[min(len(draws) - 1, int(alpha / 2 * len(draws)))]
    hi = draws[min(len(draws) - 1, int((1 - alpha / 2) * len(draws)) - 1)]
    return lo, hi


@dataclass
class MissingObservationBounds:
    """缺观察归队方向对通过份额的边界影响。"""

    share_complete_only: float
    share_if_missing_fail: float
    share_if_missing_pass: float
    complete_weight: float
    missing_weight: float

    def as_dict(self) -> dict:
        return {
            "share_complete_only": round(self.share_complete_only, 6),
            "share_if_missing_fail": round(self.share_if_missing_fail, 6),
            "share_if_missing_pass": round(self.share_if_missing_pass, 6),
            "complete_weight": round(self.complete_weight, 6),
            "missing_weight": round(self.missing_weight, 6),
        }


def missing_observation_bounds(
    complete: Sequence[PairEvidence],
    missing: Sequence[PairEvidence],
    predicate: Predicate,
) -> MissingObservationBounds:
    """把缺观察配对分别按不利/有利归队，给出份额包络。"""
    w_complete = sum(p.weight for p in complete)
    w_missing = sum(p.weight for p in missing)
    w_pass = sum(p.weight for p in complete if predicate(p))
    total = w_complete + w_missing
    return MissingObservationBounds(
        share_complete_only=(w_pass / w_complete if w_complete else math.nan),
        share_if_missing_fail=(w_pass / total if total else math.nan),
        share_if_missing_pass=(
            (w_pass + w_missing) / total if total else math.nan
        ),
        complete_weight=w_complete,
        missing_weight=w_missing,
    )
