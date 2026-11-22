"""联合可行时间引擎：钟差、顺序约束、开放经历与冲突检测。"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.engine import (  # noqa: E402
    DifferenceConstraintModel,
    build_journey_model,
    evaluate_all,
    evaluate_journey,
)
from evidence_tool.records import (  # noqa: E402
    ARRIVAL,
    DEPARTURE,
    FREE_TO_LEAVE,
    TOUR_END,
    load_bundle,
)

DATA = Path(__file__).resolve().parents[1] / "data"


class FeasibleTimeEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle(DATA)
        cls.results = evaluate_all(cls.bundle)

    def test_all_journeys_jointly_feasible_on_synthetic_data(self):
        infeasible = [j for j, r in self.results.items() if not r.feasible]
        self.assertEqual(infeasible, [])

    def test_spans_are_non_negative_under_ordering(self):
        for jid, r in self.results.items():
            if r.pickup_span is not None:
                self.assertGreaterEqual(r.pickup_span[0], 0, jid)
                self.assertLessEqual(r.pickup_span[0], r.pickup_span[1])
            if r.return_span is not None:
                self.assertGreaterEqual(r.return_span[0], 0, jid)

    def test_shared_device_offset_tightens_return_lower_bound(self):
        # 朴素独立区间会给 M191 回程下界 -7；顺序 + 联合约束把它收紧到 0
        r = self.results["M191"]
        self.assertEqual(r.return_span[0], 0.0)
        self.assertEqual(r.return_span[1], 25.0)

    def test_open_ended_journey_has_pickup_but_no_return(self):
        for jid in ("M081", "M291"):
            r = self.results[jid]
            self.assertTrue(r.open_ended)
            self.assertIsNone(r.return_span)
            self.assertIsNotNone(r.pickup_span)
            self.assertIn(FREE_TO_LEAVE, r.missing_kinds)

    def test_total_span_is_joint_sum_and_tighter_than_independent_sum(self):
        # 全程交车用时 = 去程 + 回程，四项联合求解；抵达与可离开共享
        # 设备 A 钟差，结果必须不松于两段独立区间相加
        r = self.results["M000"]
        summed = (
            r.pickup_span[0] + r.return_span[0],
            r.pickup_span[1] + r.return_span[1],
        )
        self.assertGreaterEqual(r.total_span[0], summed[0])
        self.assertLessEqual(r.total_span[1], summed[1])
        # 且仍是包含两段的合理量级（几十分钟，而非含游览的数百分钟）
        self.assertLess(r.total_span[1], 200)

    def test_negative_cycle_detected_as_infeasible(self):
        # 人为制造顺序颠倒：让“可启程”的钟面整体晚于“结束游览”，
        # 且同设备校准不足以补救时，模型应报不可行
        bundle = load_bundle(DATA)
        journey = bundle.journey("M000")
        events = bundle.events_of("M000")
        broken = dict(events)
        depart = broken[DEPARTURE]
        broken[DEPARTURE] = type(depart)(
            event=depart.event,
            journey=depart.journey,
            kind=depart.kind,
            device=depart.device,
            clock_lo=950.0,
            clock_hi=955.0,
            visible_day=depart.visible_day,
            revision=depart.revision,
        )
        model, _, _, missing = build_journey_model(
            journey, broken, bundle.calibrations
        )
        self.assertFalse(missing)
        self.assertFalse(model.solve())

    def test_same_device_difference_cancels_offset(self):
        # 同设备两事件之差不受钟差区间宽度影响（在顺序约束不绑定处）
        model = DifferenceConstraintModel(["a", "b", "d"])
        z = DifferenceConstraintModel.ZERO
        model.add("d", z, 100.0)
        model.add(z, "d", -100.0)  # 宽钟差 [-100,100]
        model.add("a", z, 10.0)
        model.add(z, "a", -10.0)
        model.add("b", z, 30.0)
        model.add(z, "b", -30.0)
        self.assertTrue(model.solve())
        lo, hi = model.diff_bounds("b", "a")
        self.assertEqual((lo, hi), (20.0, 20.0))

    def test_correction_changes_feasible_bounds(self):
        before = load_bundle(DATA, as_of="2026-06-11")
        after = load_bundle(DATA, as_of="2026-06-12")
        r_before = evaluate_journey(before, "M051")
        r_after = evaluate_journey(after, "M051")
        # rev2 把 B 钟差从 [-8,4] 改成 [-23,-19]，可启程真实时刻整体前移
        self.assertNotEqual(
            r_before.true_time_bounds[DEPARTURE],
            r_after.true_time_bounds[DEPARTURE],
        )
        self.assertLess(
            r_after.true_time_bounds[DEPARTURE][0],
            r_before.true_time_bounds[DEPARTURE][0],
        )


if __name__ == "__main__":
    unittest.main()
