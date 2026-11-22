"""差分约束引擎与线性规划参考实现的交叉验证。

Floyd-Warshall 是工具的生产引擎（纯标准库、可解释）；这里用
scipy 的线性规划在全部旅程上独立求解同一组约束，校验每段用时与
全程交车用时的区间完全一致，防止最短路径包络实现出现松紧偏差。
"""
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.engine import evaluate_all  # noqa: E402
from evidence_tool.records import (  # noqa: E402
    ARRIVAL,
    DEPARTURE,
    EVENT_ORDER,
    FREE_TO_LEAVE,
    TOUR_END,
    load_bundle,
)

DATA = Path(__file__).resolve().parents[1] / "data"
EPS = 1e-7


def lp_spans(bundle, journey_id):
    """用 LP 独立计算去程、回程与全程交车用时的可行区间。"""
    journey = bundle.journey(journey_id)
    events = bundle.events_of(journey_id)
    kinds = [k for k in EVENT_ORDER if k in events]
    devices = sorted({obs.device for obs in events.values()})
    x_index = {k: i for i, k in enumerate(kinds)}
    n = len(kinds)
    o_index = {d: n + i for i, d in enumerate(devices)}
    size = n + len(devices)

    bounds = [None] * size
    for kind in kinds:
        obs = events[kind]
        bounds[x_index[kind]] = (obs.clock_lo, obs.clock_hi)
    for device in devices:
        cal = bundle.calibrations[(journey["day"], device)]
        bounds[o_index[device]] = (cal.offset_lo, cal.offset_hi)

    matrix, vector = [], []
    for earlier, later in zip(kinds, kinds[1:]):
        row = np.zeros(size)
        row[x_index[earlier]] = 1
        row[o_index[events[earlier].device]] = 1
        row[x_index[later]] = -1
        row[o_index[events[later].device]] = -1
        matrix.append(row)
        vector.append(0.0)
    matrix = np.array(matrix)
    vector = np.array(vector)

    def span(positive_kinds, negative_kinds):
        coeff = np.zeros(size)
        for kind in positive_kinds:
            coeff[x_index[kind]] += 1
            coeff[o_index[events[kind].device]] += 1
        for kind in negative_kinds:
            coeff[x_index[kind]] -= 1
            coeff[o_index[events[kind].device]] -= 1
        low = linprog(
            c=coeff, A_ub=matrix, b_ub=vector, bounds=bounds, method="highs"
        ).fun
        high = -linprog(
            c=-coeff, A_ub=matrix, b_ub=vector, bounds=bounds, method="highs"
        ).fun
        return low, high

    out = {}
    if {ARRIVAL, DEPARTURE} <= set(kinds):
        out["pickup"] = span([DEPARTURE], [ARRIVAL])
    if {TOUR_END, FREE_TO_LEAVE} <= set(kinds):
        out["return"] = span([FREE_TO_LEAVE], [TOUR_END])
    if {ARRIVAL, DEPARTURE, TOUR_END, FREE_TO_LEAVE} <= set(kinds):
        out["total"] = span([DEPARTURE, FREE_TO_LEAVE], [ARRIVAL, TOUR_END])
    return out


class LpCrossValidationTest(unittest.TestCase):
    def test_engine_matches_linear_program_on_every_journey(self):
        bundle = load_bundle(DATA)
        engine = evaluate_all(bundle)
        for journey_id, result in engine.items():
            reference = lp_spans(bundle, journey_id)
            for segment in ("pickup", "return", "total"):
                got = getattr(result, f"{segment}_span")
                expected = reference.get(segment)
                if expected is None:
                    self.assertIsNone(got, (journey_id, segment))
                else:
                    self.assertIsNotNone(got, (journey_id, segment))
                    self.assertAlmostEqual(got[0], expected[0], delta=EPS)
                    self.assertAlmostEqual(got[1], expected[1], delta=EPS)


if __name__ == "__main__":
    unittest.main()
