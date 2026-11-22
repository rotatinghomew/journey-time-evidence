"""推广位定向规则、覆盖冲突与更正后的复查。

发布席确认投放时，把文案适用范围和各页面的定向规则一并交给工具：

* 文案的证据覆盖必须包住页面的实际访问范围，否则不能投；
* 共享同一推广位的多个页面若不能在那个位置表达必要的例外
  （``show_exceptions=false``），只能采用能覆盖全部实际访问范围的
  文案，或退回编辑调整位置；
* 内容可以按地区拆分投放；合作方已使用的原文（``accepted``）保留
  回查线索；
* 收到更正的计时关系后，对现用页面逐路由给出“站得住 / 先停投 /
  收窄”的复查结论及原因，而不是只换一张平均时长表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .claims import BufferResult, SavingsResult, _statement_targets
from .records import EvidenceBundle

HOLD = "站得住"
NARROW = "收窄"
HALT = "先停投"
ADJUST = "退回调整位置"


@dataclass
class RouteDecision:
    """一条页面路由（推广位 × 投放位置）上的投放结论。"""

    page: str
    route: str
    statement: str
    decision: str
    reach_areas: list[str]
    evidence_areas: list[str]
    show_exceptions: bool
    reasons: list[str] = field(default_factory=list)
    accepted_reference: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "route": self.route,
            "statement": self.statement,
            "decision": self.decision,
            "reach_areas": self.reach_areas,
            "evidence_areas": self.evidence_areas,
            "show_exceptions": self.show_exceptions,
            "reasons": self.reasons,
            "accepted_reference": self.accepted_reference,
        }


def _evidence_areas(result: SavingsResult | BufferResult) -> set[str]:
    return set(result.coverage.get("supported", {}).get("area", []))


def evaluate_route(
    bundle: EvidenceBundle,
    statement: dict,
    result: SavingsResult | BufferResult,
    page_row: dict,
) -> RouteDecision:
    """在单条页面路由上判定文案能否投放。"""
    _, target_areas = _statement_targets(statement)
    reach = set(page_row["areas"])
    evidence = _evidence_areas(result)
    show_exceptions = bool(page_row["show_exceptions"])

    decision = RouteDecision(
        page=page_row["page"],
        route=page_row["route"],
        statement=statement["statement"],
        decision=HALT,
        reach_areas=sorted(reach),
        evidence_areas=sorted(evidence),
        show_exceptions=show_exceptions,
        accepted_reference=page_row.get("accepted"),
    )

    if not result.passed:
        decision.decision = HALT
        decision.reasons.append("证据评估未通过：" + "；".join(result.reasons))
        return decision

    uncovered = reach - evidence
    if not uncovered:
        decision.decision = HOLD
        decision.reasons.append("证据覆盖包住该路由的全部实际访问地区")
        return decision

    if show_exceptions:
        # 能显示例外时，允许收窄到证据覆盖地区，并把例外展示出来
        decision.decision = NARROW
        decision.reasons.append(
            "该位置可展示范围限制，收窄至证据覆盖地区；"
            f"需向 {sorted(uncovered)} 访问者展示例外"
        )
    else:
        decision.decision = ADJUST
        decision.reasons.append(
            "证据不覆盖 "
            f"{sorted(uncovered)}，且该推广位不能表达必要例外；"
            "需换成覆盖全部访问范围的文案，或退回编辑调整位置"
        )
    return decision


def evaluate_placement(
    bundle: EvidenceBundle,
    results: dict[str, SavingsResult | BufferResult],
) -> list[RouteDecision]:
    """对每条文案在其登记页面的全部路由上给出投放结论。"""
    statements = {s["statement"]: s for s in bundle.statements}
    decisions: list[RouteDecision] = []
    for page_row in bundle.pages:
        # 一个推广位可能被多条文案登记；逐文案评估，再合成位置结论
        for sid, statement in statements.items():
            if statement["page"] != page_row["page"]:
                continue
            result = results.get(sid)
            if result is None:
                continue
            decisions.append(
                evaluate_route(bundle, statement, result, page_row)
            )
    return decisions


def review_after_correction(
    before: dict[str, SavingsResult | BufferResult],
    after: dict[str, SavingsResult | BufferResult],
    before_decisions: list[RouteDecision],
    after_decisions: list[RouteDecision],
) -> list[dict]:
    """对比更正前后的证据，逐条现用页面给出复查结论与变化原因。

    输出的是“结论为什么变化”的可回查记录，不是新的平均时长表：
    覆盖地区、通过状态、关键份额/迟尾的变化都逐项列出。
    """
    review: list[dict] = []
    after_index = {(d.page, d.route, d.statement): d for d in after_decisions}
    for old in before_decisions:
        key = (old.page, old.route, old.statement)
        new = after_index.get(key)
        entry: dict = {
            "page": old.page,
            "route": old.route,
            "statement": old.statement,
            "before_decision": old.decision,
            "after_decision": new.decision if new else HALT,
            "changes": [],
        }
        b_result = before.get(old.statement)
        a_result = after.get(old.statement)
        if b_result is None or a_result is None:
            entry["changes"].append("更正后缺少可比较的证据结果")
        else:
            if b_result.passed != a_result.passed:
                entry["changes"].append(
                    f"证据通过状态：{'通过' if b_result.passed else '未通过'}"
                    f" → {'通过' if a_result.passed else '未通过'}"
                )
            b_areas = set(
                b_result.coverage.get("supported", {}).get("area", [])
            )
            a_areas = set(
                a_result.coverage.get("supported", {}).get("area", [])
            )
            if b_areas != a_areas:
                entry["changes"].append(
                    f"证据覆盖地区：{sorted(b_areas)} → {sorted(a_areas)}"
                )
            if isinstance(b_result, SavingsResult) and isinstance(
                a_result, SavingsResult
            ):
                for label in ("conservative", "nominal", "optimistic"):
                    old_share = b_result.estimates.get(label, {}).get("share")
                    new_share = a_result.estimates.get(label, {}).get("share")
                    if old_share != new_share:
                        entry["changes"].append(
                            f"{label} 加权通过份额：{old_share} → {new_share}"
                        )
                old_missing = b_result.missing_bounds or {}
                new_missing = a_result.missing_bounds or {}
                for key in (
                    "share_if_missing_fail",
                    "share_if_missing_pass",
                    "missing_weight",
                ):
                    if old_missing.get(key) != new_missing.get(key):
                        entry["changes"].append(
                            f"缺观察敏感性 {key}："
                            f"{old_missing.get(key)} → {new_missing.get(key)}"
                        )
            if isinstance(b_result, BufferResult) and isinstance(
                a_result, BufferResult
            ):
                old_tail = b_result.tail.get("worst_min_buffer")
                new_tail = a_result.tail.get("worst_min_buffer")
                if old_tail != new_tail:
                    entry["changes"].append(
                        f"最差可保证缓冲（迟尾）：{old_tail} → {new_tail} 分钟"
                    )
            entry["changes"].extend(
                f"更正后：{reason}" for reason in a_result.reasons
            )
        if not entry["changes"]:
            entry["changes"].append("关键结论与覆盖范围均未变化，原文案站得住")
        review.append(entry)
    return review
