"""钟差校准、相邻事件顺序与共用钟差下的联合可行时间。

每个旅程的现场记录给出设备钟面分钟上下界，真实分钟满足
``t = 钟面分钟 + 设备钟差``；同一设备同一日的所有事件共用一个未知
钟差。模型包含三类变量：

* 钟面变量 ``x_k``：事件 ``k`` 的设备读数，有区间边界；
* 钟差变量 ``o_d``：设备 ``d`` 当日的公用未知钟差，有校准区间，
  同设备事件共享同一个变量（钟差在同设备差值中自动抵消）；
* 真实时刻变量 ``t_k = x_k + o_d``，由两条差分约束夹住。

相邻事件必须满足真实时刻不颠倒
``t_到交车点 <= t_可启程 <= t_结束游览 <= t_可离开``。

全部约束都是 ``u - v <= w`` 形式的差分约束。用 Floyd-Warshall 求全源
最短路径即可同时得到：

1. 是否存在联合可行赋值（对角线上出现负环即记录互相冲突）；
2. 任意两个真实时刻之差的可证实最紧上下界；
3. 每个真实时刻自身的可行区间。

引擎只输出可证实范围，不替未结束的经历补终点，也不把缺记录当成正证。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .records import (
    DEPARTURE,
    EVENT_ORDER,
    FREE_TO_LEAVE,
    TOUR_END,
    ARRIVAL,
    Calibration,
    EvidenceBundle,
    EventObservation,
)

INF = math.inf
EPS = 1e-9


def _clean(bounds: tuple[float, float]) -> tuple[float, float]:
    """把浮点负零归一为 0，保持输出稳定可读。"""
    lo, hi = bounds
    return (0.0 if abs(lo) < EPS else lo, 0.0 if abs(hi) < EPS else hi)


@dataclass
class JourneyFeasibility:
    """单个旅程在截止日资料下的可行时间结论。"""

    journey: str
    feasible: bool
    present_kinds: tuple[str, ...]
    missing_kinds: tuple[str, ...]
    #: 未结束的经历（最后一条上报不能自动封口）
    open_ended: bool
    #: 该旅程引用但截止日缺少有效校准的设备列表
    missing_calibrations: tuple[str, ...]
    #: 去程用时（抵达可接受交车点 → 可以启程）的可行区间
    pickup_span: Optional[tuple[float, float]] = None
    #: 回程用时（结束行程 → 旅客可自行离开）的可行区间
    return_span: Optional[tuple[float, float]] = None
    #: 交车相关总用时（去程 + 回程）的可行区间。
    #: 注意不是“抵达→可离开”的整段时间（那含游览本身），而是两段
    #: 旅客交车等待之和；在模型内对四项联合求解，保留同设备钟差的
    #: 抵消效应，避免分段独立区间相加变松。
    total_span: Optional[tuple[float, float]] = None
    #: 各事件真实时刻的可行区间
    true_time_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: 冲突原因（负环等），便于覆盖说明引用
    reason: Optional[str] = None

    @property
    def pickup_observed(self) -> bool:
        return self.pickup_span is not None

    @property
    def return_observed(self) -> bool:
        return self.return_span is not None


class DifferenceConstraintModel:
    """差分约束 ``u - v <= w`` 的全源最短路径求解器。"""

    ZERO = "ZERO"

    def __init__(self, nodes: list[str]) -> None:
        self.nodes = [self.ZERO] + nodes
        self.index = {name: i for i, name in enumerate(self.nodes)}
        n = len(self.nodes)
        self.dist = [[INF] * n for _ in range(n)]
        for i in range(n):
            self.dist[i][i] = 0.0

    def add(self, u: str, v: str, bound: float) -> None:
        """加入约束 ``u - v <= bound``。"""
        iu, iv = self.index[u], self.index[v]
        if bound < self.dist[iu][iv]:
            self.dist[iu][iv] = float(bound)

    def solve(self) -> bool:
        """Floyd-Warshall；返回 False 表示存在负环（无可行解）。"""
        d = self.dist
        n = len(self.nodes)
        for k in range(n):
            dk = d[k]
            for i in range(n):
                dik = d[i][k]
                if dik == INF:
                    continue
                di = d[i]
                for j in range(n):
                    dkj = dk[j]
                    if dkj == INF:
                        continue
                    candidate = dik + dkj
                    if candidate < di[j]:
                        di[j] = candidate
        return not any(d[i][i] < -EPS for i in range(n))

    def variable_bounds(self, name: str) -> tuple[float, float]:
        """单变量相对零节点的可行区间 ``[lo, hi]``。"""
        i = self.index[name]
        z = self.index[self.ZERO]
        hi = self.dist[i][z]
        lo = -self.dist[z][i]
        return lo, hi

    def diff_bounds(self, positive: str, negative: str) -> tuple[float, float]:
        """``positive - negative`` 的紧上下界。"""
        ip, ineg = self.index[positive], self.index[negative]
        hi = self.dist[ip][ineg]
        lo = -self.dist[ineg][ip]
        return lo, hi

    def expression_bounds(
        self,
        positive: list[str],
        negative: list[str],
    ) -> tuple[float, float]:
        """线性式 ``sum(positive) - sum(negative)`` 的紧上下界。

        差分约束（全么模）下线性式的极值可由最短路径包络得到：把正、
        负节点做最小费用两两配对，上界为配对路径和的最小值；下界对换
        正负号后同理。单变量差（各一项）时退化为普通最短路。
        """
        n_pos, n_neg = len(positive), len(negative)
        if n_pos == 1 and n_neg == 1:
            return self.diff_bounds(positive[0], negative[0])

        def min_assignment(left: list[str], right: list[str]) -> float:
            # 小规模（本业务至多 2×2）：枚举全部配对，取路径和最小值
            import itertools

            best = INF
            for perm in itertools.permutations(range(len(right))):
                cost = 0.0
                for i, j in enumerate(perm):
                    cost += self.dist[self.index[left[i]]][
                        self.index[right[j]]
                    ]
                best = min(best, cost)
            return best

        hi = min_assignment(positive, negative)
        lo = -min_assignment(negative, positive)
        return lo, hi


def _true_node(kind: str) -> str:
    return f"t:{kind}"


def _clock_node(kind: str) -> str:
    return f"x:{kind}"


def build_journey_model(
    journey: dict,
    events: dict[str, EventObservation],
    calibrations: dict[tuple[str, str], Calibration],
) -> tuple[Optional[DifferenceConstraintModel], list[str], list[str], list[str]]:
    """构造单个旅程的差分约束模型，并报告缺失项。"""
    kinds_present = [k for k in EVENT_ORDER if k in events]
    kinds_missing = [k for k in EVENT_ORDER if k not in events]
    devices = sorted({obs.device for obs in events.values()})

    missing_cals = sorted(
        {
            device
            for device in devices
            if (journey["day"], device) not in calibrations
        }
    )
    if missing_cals:
        return None, kinds_present, kinds_missing, missing_cals

    clock_nodes = [_clock_node(k) for k in kinds_present]
    true_nodes = [_true_node(k) for k in kinds_present]
    model = DifferenceConstraintModel(clock_nodes + devices + true_nodes)
    z = DifferenceConstraintModel.ZERO

    # 钟面/钟差变量区间，以及 t_k = x_k + o_d 的两条夹约束
    for kind in kinds_present:
        obs = events[kind]
        cal = calibrations[(journey["day"], obs.device)]
        xk, tk, od = _clock_node(kind), _true_node(kind), obs.device

        # clo <= x_k <= chi
        model.add(xk, z, obs.clock_hi)
        model.add(z, xk, -obs.clock_lo)
        # olo <= o_d <= ohi（同设备只加一次，天然共享）
        model.add(od, z, cal.offset_hi)
        model.add(z, od, -cal.offset_lo)
        # t_k - o_d <= chi 且 o_d - t_k <= -clo
        model.add(tk, od, obs.clock_hi)
        model.add(od, tk, -obs.clock_lo)

    # 相邻事件真实时刻顺序：t_earlier <= t_later
    for earlier, later in zip(kinds_present, kinds_present[1:]):
        model.add(_true_node(earlier), _true_node(later), 0.0)

    return model, kinds_present, kinds_missing, []


def evaluate_journey(bundle: EvidenceBundle, journey_id: str) -> JourneyFeasibility:
    """评估单个旅程，给出可行性、去/回程用时区间与开放状态。"""
    journey = bundle.journey(journey_id)
    events = bundle.events_of(journey_id)

    model, present, missing, missing_cals = build_journey_model(
        journey, events, bundle.calibrations
    )
    if missing_cals:
        return JourneyFeasibility(
            journey=journey_id,
            feasible=False,
            present_kinds=tuple(present),
            missing_kinds=tuple(missing),
            open_ended=FREE_TO_LEAVE in missing,
            missing_calibrations=tuple(missing_cals),
            reason="缺少有效设备钟差校准",
        )

    feasible = model.solve()
    if not feasible:
        return JourneyFeasibility(
            journey=journey_id,
            feasible=False,
            present_kinds=tuple(present),
            missing_kinds=tuple(missing),
            open_ended=FREE_TO_LEAVE in missing,
            missing_calibrations=(),
            reason="差分约束出现负环：记录之间不存在联合可行的钟差与时刻",
        )

    true_bounds = {
        kind: _clean(model.variable_bounds(_true_node(kind))) for kind in present
    }

    pickup = (
        _clean(model.diff_bounds(_true_node(DEPARTURE), _true_node(ARRIVAL)))
        if ARRIVAL in present and DEPARTURE in present
        else None
    )
    return_span = (
        _clean(model.diff_bounds(_true_node(FREE_TO_LEAVE), _true_node(TOUR_END)))
        if TOUR_END in present and FREE_TO_LEAVE in present
        else None
    )
    # 全程交车用时 = (可启程-到交车点) + (可离开-结束游览)。
    # 四项在同一约束模型内联合求解：两段各自跨设备，但到交车点与可
    # 离开共享设备 A 的钟差，联合处理比独立区间相加更紧。
    required = {ARRIVAL, DEPARTURE, TOUR_END, FREE_TO_LEAVE}
    total_span = (
        _clean(
            model.expression_bounds(
                positive=[
                    _true_node(DEPARTURE),
                    _true_node(FREE_TO_LEAVE),
                ],
                negative=[
                    _true_node(ARRIVAL),
                    _true_node(TOUR_END),
                ],
            )
        )
        if required <= set(present)
        else None
    )

    return JourneyFeasibility(
        journey=journey_id,
        feasible=True,
        present_kinds=tuple(present),
        missing_kinds=tuple(missing),
        open_ended=FREE_TO_LEAVE in missing,
        missing_calibrations=(),
        pickup_span=pickup,
        return_span=return_span,
        total_span=total_span,
        true_time_bounds=true_bounds,
    )


def evaluate_all(bundle: EvidenceBundle) -> dict[str, JourneyFeasibility]:
    """对资料中的全部旅程给出可行时间结论。"""
    return {
        row["journey"]: evaluate_journey(bundle, row["journey"])
        for row in bundle.journeys
    }
