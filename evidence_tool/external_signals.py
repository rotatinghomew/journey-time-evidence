"""外部信号筛查：感受调查与关闭期缺记录。

这两类资料都不能直接给适用范围作正证：

* **只含准时行程的感受调查** 是选择性样本——迟尾经历被排除在外，
  满意度不能外推为全旅客的时间证据；
* **关闭期间的缺记录** 是覆盖缺口而非“零用时”，只能进入覆盖说明，
  不能填补为观察值。

工具把它们显式标记为不可作正证，并说明原因，避免被悄悄并入证据集。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Sequence


@dataclass
class SurveyRecord:
    """一条感受调查记录的最小结构。"""

    survey_id: str
    area: str
    window: str
    on_time_only: bool
    respondents: int
    score: Optional[float] = None


@dataclass
class ScreeningOutcome:
    """外部信号筛查结论。"""

    admissible_positive: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    coverage_gaps: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "admissible_positive": self.admissible_positive,
            "rejected": self.rejected,
            "coverage_gaps": self.coverage_gaps,
        }


def screen_surveys(surveys: Sequence[SurveyRecord]) -> ScreeningOutcome:
    """筛查感受调查：只含准时行程的调查不得作时间文案的正证。"""
    outcome = ScreeningOutcome()
    for survey in surveys:
        row = {
            "survey_id": survey.survey_id,
            "area": survey.area,
            "window": survey.window,
            "respondents": survey.respondents,
            "score": survey.score,
        }
        if survey.on_time_only:
            outcome.rejected.append(
                {
                    **row,
                    "reason": "样本仅含准时行程，迟尾被系统性排除，"
                    "不能外推为全旅客的时间正证",
                }
            )
        else:
            outcome.admissible_positive.append(
                {**row, "note": "可作背景参考，仍不能替代事件记录的用时区间"}
            )
    return outcome


def parse_closure_window(spec: dict) -> tuple[date, date]:
    """解析 ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`` 关闭窗。"""
    start = date.fromisoformat(spec["start"])
    end = date.fromisoformat(spec["end"])
    if end < start:
        raise ValueError(f"关闭窗结束早于开始：{spec}")
    return start, end


def screen_closure_gaps(
    observed_days: Sequence[str],
    closure_windows: Sequence[dict],
    area: str,
) -> ScreeningOutcome:
    """把关闭期内的缺记录识别为覆盖缺口，而不是观察证据。

    ``observed_days`` 为该地区实际有事件记录的日期；落在关闭窗内的
    日期不要求有记录，窗内没有记录只登记为缺口说明。
    """
    outcome = ScreeningOutcome()
    observed = {date.fromisoformat(d) for d in observed_days}
    for spec in closure_windows:
        start, end = parse_closure_window(spec)
        window_days = [
            date.fromordinal(start.toordinal() + i)
            for i in range((end - start).days + 1)
        ]
        covered = sum(1 for day in window_days if day in observed)
        outcome.coverage_gaps.append(
            {
                "area": area,
                "window": f"{start.isoformat()}~{end.isoformat()}",
                "days": len(window_days),
                "days_with_records": covered,
                "reason": "关闭期缺记录是覆盖缺口，不能填补为零用时或正证",
            }
        )
    return outcome
