"""配对可比性、净节省区间与开放配对排除规则。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.engine import evaluate_all  # noqa: E402
from evidence_tool.matching import (  # noqa: E402
    build_pair_evidence,
    interval_allows,
    interval_guarantees,
)
from evidence_tool.records import load_bundle  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


class PairEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle(DATA)
        cls.feasibility = evaluate_all(cls.bundle)
        cls.pairs = {
            p.pair: p
            for p in build_pair_evidence(cls.bundle, cls.feasibility)
        }

    def test_singleton_pair_is_not_eligible_comparison(self):
        # M10、M26 只有送车一程，不能构成传统对照
        for pid in ("M10", "M26"):
            pair = self.pairs[pid]
            self.assertFalse(pair.eligible)
            self.assertTrue(
                any("完整对照" in r for r in pair.exclusion_reasons)
            )

    def test_open_pair_kept_out_of_return_and_total_evidence(self):
        # M08 的送车一程 M081 缺“可离开”：去程可证，回程/全程不得封口
        pair = self.pairs["M08"]
        self.assertTrue(pair.open_ended)
        self.assertIsNotNone(pair.pickup_saving)
        self.assertIsNone(pair.return_saving)
        self.assertIsNone(pair.total_saving)
        self.assertTrue(
            any("尚未结束" in r for r in pair.exclusion_reasons)
        )

    def test_saving_interval_is_interval_difference_not_best_column(self):
        pair = self.pairs["M00"]
        trad = self.feasibility[pair.traditional]
        delivery = self.feasibility[pair.delivery]
        expected_pickup = (
            trad.pickup_span[0] - delivery.pickup_span[1],
            trad.pickup_span[1] - delivery.pickup_span[0],
        )
        self.assertEqual(pair.pickup_saving, expected_pickup)
        # 区间必须同时容纳“没省时间”的可能，文案不能挑最有利的一列
        self.assertLess(pair.total_saving[0], pair.total_saving[1])

    def test_version_mismatch_recorded_as_coverage_caveat(self):
        # v2 送车与 v1 传统对照时，版本差异保留在覆盖说明里
        pair = self.pairs["M16"]
        self.assertIn("version", pair.coverage_mismatches)
        self.assertEqual(
            pair.coverage_mismatches["version"], ("v1", "v2")
        )

    def test_threshold_predicates(self):
        self.assertTrue(interval_guarantees((10.0, 20.0), 10.0))
        self.assertFalse(interval_guarantees((9.9, 20.0), 10.0))
        self.assertTrue(interval_allows((-5.0, 20.0), 10.0))
        self.assertFalse(interval_allows((-5.0, 9.0), 10.0))

    def test_total_saving_uses_joint_model_directly(self):
        # 全程净节省来自模型内“抵达→可离开”的直接区间，保留同设备
        # 钟差抵消效应；与分段净节省相加相比，口径不同但都可证实
        pair = self.pairs["M00"]
        trad = self.feasibility[pair.traditional]
        delivery = self.feasibility[pair.delivery]
        expected = (
            trad.total_span[0] - delivery.total_span[1],
            trad.total_span[1] - delivery.total_span[0],
        )
        self.assertEqual(pair.total_saving, expected)
        self.assertIsInstance(pair.total_saving[0], float)


if __name__ == "__main__":
    unittest.main()
