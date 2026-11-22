"""外部信号筛查：准时行程调查与关闭期缺记录。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.external_signals import (  # noqa: E402
    SurveyRecord,
    parse_closure_window,
    screen_closure_gaps,
    screen_surveys,
)


class ExternalSignalTest(unittest.TestCase):
    def test_on_time_only_survey_is_not_positive_evidence(self):
        surveys = [
            SurveyRecord("q1", "西湾", "上午", True, 100, 4.8),
            SurveyRecord("q2", "西湾", "上午", False, 120, 4.2),
        ]
        outcome = screen_surveys(surveys)
        self.assertEqual([r["survey_id"] for r in outcome.rejected], ["q1"])
        self.assertEqual(
            [r["survey_id"] for r in outcome.admissible_positive], ["q2"]
        )
        self.assertIn("迟尾", outcome.rejected[0]["reason"])

    def test_closure_gap_is_coverage_gap_not_zero_observation(self):
        outcome = screen_closure_gaps(
            observed_days=["2026-06-01"],
            closure_windows=[
                {"start": "2026-06-02", "end": "2026-06-04"}
            ],
            area="西湾",
        )
        gap = outcome.coverage_gaps[0]
        self.assertEqual(gap["days"], 3)
        self.assertEqual(gap["days_with_records"], 0)
        self.assertIn("覆盖缺口", gap["reason"])

    def test_closure_window_rejects_reversed_dates(self):
        with self.assertRaises(ValueError):
            parse_closure_window(
                {"start": "2026-06-05", "end": "2026-06-01"}
            )


if __name__ == "__main__":
    unittest.main()
