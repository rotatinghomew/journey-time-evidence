"""两类文案的证据评估规则。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.claims import (  # noqa: E402
    OUTBOUND_DEPARTURE_LIMIT,
    evaluate_buffer_statement,
    evaluate_savings_statement,
)
from evidence_tool.engine import evaluate_all  # noqa: E402
from evidence_tool.matching import build_pair_evidence  # noqa: E402
from evidence_tool.records import (  # noqa: E402
    BUFFER_CLAIM,
    SAVINGS_CLAIM,
    load_bundle,
)

DATA = Path(__file__).resolve().parents[1] / "data"


class ClaimEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle(DATA)
        cls.feasibility = evaluate_all(cls.bundle)
        cls.pairs = build_pair_evidence(cls.bundle, cls.feasibility)
        cls.statements = {
            s["statement"]: s for s in cls.bundle.statements
        }

    def test_savings_claim_shows_three_uncertainty_lenses(self):
        result = evaluate_savings_statement(
            self.bundle, self.pairs, self.statements["s1"],
            replicates=500,
        )
        self.assertEqual(result.segment, "total")
        for label in ("conservative", "nominal", "optimistic"):
            self.assertIn(label, result.estimates)
        # 合成资料下没有任何配对能保证省 30 分钟：保守口径份额为 0
        self.assertEqual(result.estimates["conservative"]["share"], 0.0)
        self.assertFalse(result.passed)
        # 净节省分布逐对给出区间，而不是单个平均值
        self.assertTrue(all("saving_lo" in d for d in result.distribution))

    def test_savings_coverage_cannot_silently_generalize(self):
        result = evaluate_savings_statement(
            self.bundle, self.pairs, self.statements["s1"],
            replicates=500,
        )
        supported_areas = result.coverage["supported"]["area"]
        self.assertEqual(supported_areas, ["西湾"])  # 不得推广到东岸
        # 开放配对必须显式列在覆盖说明里
        self.assertIn("M08", result.coverage["open_or_missing_pairs"])

    def test_dual_area_statement_expands_targeting(self):
        result = evaluate_savings_statement(
            self.bundle, self.pairs, self.statements["s3"],
            replicates=500,
        )
        self.assertEqual(
            sorted(result.coverage["supported"]["area"]),
            ["东岸", "西湾"],
        )

    def test_pickup_segment_keeps_open_pair_as_evidence(self):
        # 仅去程口径下，M08 虽然整体开放，去程区间仍是有效正证候选
        result = evaluate_savings_statement(
            self.bundle,
            self.pairs,
            self.statements["s1"],
            segment="pickup",
            replicates=500,
        )
        self.assertIn("M08", result.eligible_pairs)

    def test_scenario_filter_narrows_population_and_is_recorded(self):
        statement = dict(self.statements["s1"])
        result = evaluate_savings_statement(
            self.bundle,
            self.pairs,
            statement,
            scenario_filters={"pickup": "民宿", "window": "傍晚"},
            replicates=500,
        )
        # 收窄后证据集只含民宿/傍晚配对，数量少于未收窄的 s1 集合
        unfiltered = evaluate_savings_statement(
            self.bundle, self.pairs, statement, replicates=500
        )
        self.assertLess(
            len(result.eligible_pairs), len(unfiltered.eligible_pairs)
        )
        self.assertEqual(
            result.coverage["scenario_filters"],
            {"pickup": "民宿", "window": "傍晚"},
        )
        for pair_id in result.eligible_pairs:
            j = self.bundle.journey(
                next(p.delivery for p in self.pairs if p.pair == pair_id)
            )
            self.assertEqual(j["pickup"], "民宿")
            self.assertEqual(j["window"], "傍晚")

    def test_shift_window_pairs_flagged_in_coverage(self):
        result = evaluate_savings_statement(
            self.bundle, self.pairs, self.statements["s1"],
            replicates=500,
        )
        # M00 的 basis 为“班窗可能偏移”，必须在覆盖说明中显式提示
        self.assertIn("M00", result.coverage["shift_window_pairs"])

    def test_buffer_claim_uses_same_journey_for_both_legs(self):
        result = evaluate_buffer_statement(
            self.bundle, self.feasibility, self.statements["s2"], self.pairs
        )
        # 每个入选旅程都必须同时有去程与回程节点（同一行程联合评估）
        for jid in result.eligible_journeys:
            f = self.feasibility[jid]
            self.assertIsNotNone(f.pickup_span)
            self.assertIsNotNone(f.return_span)
            self.assertLessEqual(
                f.true_time_bounds["可启程"][1], OUTBOUND_DEPARTURE_LIMIT
            )
        # 迟尾：最差可保证缓冲仍为正且被量化
        self.assertGreaterEqual(result.tail["worst_min_buffer"], 0)
        # 0.9 可靠性在 6/7 份额下不达标
        self.assertFalse(result.passed)

    def test_open_journey_excluded_from_buffer_denominator(self):
        result = evaluate_buffer_statement(
            self.bundle, self.feasibility, self.statements["s2"], self.pairs
        )
        self.assertIn("M291", result.excluded["经历未结束或缺节点"])
        self.assertNotIn("M291", result.eligible_journeys)

    def test_buffer_tail_recomputes_under_correction(self):
        # 校准更正后，同一证据集的迟尾缓冲应当变化而不是只换平均值
        before_bundle = load_bundle(DATA, as_of="2026-06-25")
        before_feas = evaluate_all(before_bundle)
        before_pairs = build_pair_evidence(before_bundle, before_feas)
        before = evaluate_buffer_statement(
            before_bundle, before_feas, self.statements["s2"], before_pairs
        )
        after = evaluate_buffer_statement(
            self.bundle, self.feasibility, self.statements["s2"], self.pairs
        )
        self.assertNotEqual(
            before.tail["worst_min_buffer"],
            after.tail["worst_min_buffer"],
        )


if __name__ == "__main__":
    unittest.main()
