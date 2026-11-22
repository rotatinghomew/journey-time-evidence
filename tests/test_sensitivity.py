"""敏感性：加权份额、Wilson、自助与缺观察包络。"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.matching import PairEvidence  # noqa: E402
from evidence_tool.sensitivity import (  # noqa: E402
    missing_observation_bounds,
    weighted_bootstrap,
    weighted_share,
    wilson_interval,
)


def _pair(pid, weight, saving=None, open_ended=False, eligible=True):
    return PairEvidence(
        pair=pid,
        weight=weight,
        basis="班窗相同",
        traditional=f"{pid}T",
        delivery=f"{pid}D",
        eligible=eligible,
        open_ended=open_ended,
        pickup_saving=saving,
        return_saving=saving,
        total_saving=None if open_ended else saving,
    )


class SensitivityTest(unittest.TestCase):
    def test_wilson_brackets_point_estimate(self):
        low, high = wilson_interval(3.0, 4.0, 0.9)
        self.assertLess(low, 0.75 < high)

    def test_weighted_share_respects_weights(self):
        pairs = [
            _pair("a", 0.5, saving=(30.0, 40.0)),
            _pair("b", 1.0, saving=(0.0, 10.0)),
        ]
        est = weighted_share(
            pairs, lambda p: p.total_saving[0] >= 25, 0.9, "t"
        )
        # 只有权重 0.5 的配对通过，份额 = 0.5/1.5
        self.assertAlmostEqual(est.share, 1 / 3)

    def test_bootstrap_is_reproducible_and_brackets_share(self):
        pairs = [_pair(f"p{i}", 1.0, saving=(30.0, 40.0) if i % 2 else (0, 5))
                 for i in range(20)]
        pred = lambda p: p.total_saving[0] >= 25
        lo, hi = weighted_bootstrap(pairs, pred, 0.9, 2000, seed=42)
        lo2, hi2 = weighted_bootstrap(pairs, pred, 0.9, 2000, seed=42)
        self.assertEqual((lo, hi), (lo2, hi2))
        self.assertLessEqual(lo, 0.5 <= hi)

    def test_missing_observation_envelope(self):
        complete = [
            _pair("a", 1.0, saving=(30.0, 40.0)),
            _pair("b", 1.0, saving=(0.0, 5.0)),
        ]
        missing = [_pair("c", 1.0, open_ended=True, eligible=False)]
        bounds = missing_observation_bounds(
            complete, missing, lambda p: p.total_saving and p.total_saving[0] >= 25
        )
        self.assertAlmostEqual(bounds.share_complete_only, 0.5)
        self.assertAlmostEqual(bounds.share_if_missing_fail, 1 / 3)
        self.assertAlmostEqual(bounds.share_if_missing_pass, 2 / 3)
        self.assertEqual(bounds.missing_weight, 1.0)

    def test_zero_trials_returns_nan_not_crash(self):
        low, high = wilson_interval(0, 0, 0.9)
        self.assertTrue(math.isnan(low) and math.isnan(high))


if __name__ == "__main__":
    unittest.main()
