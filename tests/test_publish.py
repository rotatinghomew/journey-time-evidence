"""推广位定向、覆盖冲突与更正复查。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.claims import BufferResult, SavingsResult  # noqa: E402
from evidence_tool.publish import (  # noqa: E402
    ADJUST,
    HOLD,
    NARROW,
    RouteDecision,
    evaluate_placement,
    evaluate_route,
    review_after_correction,
)
from evidence_tool.records import load_bundle  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


def _savings(statement, passed, areas):
    return SavingsResult(
        statement=statement,
        passed=passed,
        threshold_minutes=30,
        reliability=0.5,
        confidence=0.9,
        segment="total",
        coverage={"supported": {"area": areas}},
    )


class PlacementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle(DATA)
        cls.statements = {
            s["statement"]: s for s in cls.bundle.statements
        }

    def test_dual_area_slot_rejects_single_area_claim_without_exception(self):
        result = _savings("s1", True, ["西湾"])
        home_travel = next(
            p for p in self.bundle.pages
            if p["page"] == "home" and p["route"] == "旅游首页"
        )
        decision = evaluate_route(
            self.bundle, self.statements["s1"], result, home_travel
        )
        self.assertEqual(decision.decision, ADJUST)
        self.assertIn("东岸", decision.reasons[0])

    def test_single_area_route_accepts_matching_claim(self):
        result = _savings("s1", True, ["西湾"])
        hotel = next(
            p for p in self.bundle.pages
            if p["route"] == "合作酒店首页"
        )
        decision = evaluate_route(
            self.bundle, self.statements["s1"], result, hotel
        )
        self.assertEqual(decision.decision, HOLD)
        # 合作方已用原文保留回查线索
        self.assertEqual(decision.accepted_reference, "s1")

    def test_exception_capable_slot_allows_narrowing(self):
        result = _savings("s2", True, ["西岸"])
        detail = next(p for p in self.bundle.pages if p["page"] == "detail")
        decision = evaluate_route(
            self.bundle, self.statements["s2"], result, detail
        )
        self.assertEqual(decision.decision, NARROW)
        self.assertTrue(any("例外" in r for r in decision.reasons))

    def test_failed_evidence_halts_everywhere(self):
        result = _savings("s1", False, ["西湾"])
        decisions = evaluate_placement(
            self.bundle, {"s1": result, "s3": _savings("s3", False, [])}
        )
        self.assertTrue(all(d.decision == "先停投" for d in decisions))

    def test_region_split_allows_separate_route_decisions(self):
        # 同一条双区文案若只在西湾拿到证据：双区首页需调整位置，
        # 但合作酒店首页（仅西湾）可以站得住——支持按地区拆分投放
        result = _savings("s1", True, ["西湾"])
        decisions = {
            (d.page, d.route): d
            for d in evaluate_placement(self.bundle, {"s1": result})
        }
        self.assertEqual(
            decisions[("home", "旅游首页")].decision, ADJUST
        )
        self.assertEqual(
            decisions[("home", "合作酒店首页")].decision, HOLD
        )

    def test_review_explains_why_conclusion_changed(self):
        before_results = {
            "s2": BufferResult(
                statement="s2", passed=True, buffer_minutes=45,
                reliability=0.9, confidence=0.9,
                coverage={"supported": {"area": ["东岸"]}},
                tail={"worst_min_buffer": 58.0},
            )
        }
        after_results = {
            "s2": BufferResult(
                statement="s2", passed=False, buffer_minutes=45,
                reliability=0.9, confidence=0.9,
                coverage={"supported": {"area": ["东岸"]}},
                tail={"worst_min_buffer": 50.0},
                reasons=["份额置信下界低于可靠性要求"],
            )
        }
        before_decisions = [
            RouteDecision(
                page="detail", route="产品详情", statement="s2",
                decision=HOLD, reach_areas=["东岸"], evidence_areas=["东岸"],
                show_exceptions=True,
            )
        ]
        after_decisions = [
            RouteDecision(
                page="detail", route="产品详情", statement="s2",
                decision="先停投", reach_areas=["东岸"],
                evidence_areas=["东岸"], show_exceptions=True,
                reasons=["份额置信下界低于可靠性要求"],
            )
        ]
        review = review_after_correction(
            before_results, after_results,
            before_decisions, after_decisions,
        )
        entry = review[0]
        self.assertEqual(entry["before_decision"], HOLD)
        self.assertEqual(entry["after_decision"], "先停投")
        self.assertTrue(
            any("58.0 → 50.0" in c for c in entry["changes"]),
            entry["changes"],
        )


if __name__ == "__main__":
    unittest.main()
