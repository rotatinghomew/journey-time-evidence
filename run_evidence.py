#!/usr/bin/env python3
"""时间文案证据工具的命令行入口。

用法：

    python3 run_evidence.py evaluate --data data --as-of 2026-06-11
    python3 run_evidence.py evaluate --data data            # 全部可见修订
    python3 run_evidence.py review --before old.json --after new.json
    python3 run_evidence.py pairs --data data
    python3 run_evidence.py journeys --data data

``evaluate`` 输出的 JSON 报告包含：截止日与被挡修订、逐旅程可行性、
配对净节省、两类文案的证据结论（含敏感性与覆盖说明）、以及每条页面
路由的投放结论。``review`` 对比两次评估，给出更正后的复查结论。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evidence_tool.claims import (  # noqa: E402
    BufferResult,
    SavingsResult,
    evaluate_buffer_statement,
    evaluate_savings_statement,
)
from evidence_tool.engine import evaluate_all  # noqa: E402
from evidence_tool.matching import build_pair_evidence  # noqa: E402
from evidence_tool.publish import (  # noqa: E402
    evaluate_placement,
    review_after_correction,
)
from evidence_tool.records import (  # noqa: E402
    BUFFER_CLAIM,
    SAVINGS_CLAIM,
    load_bundle,
)

def _feasibility_row(result) -> dict:
    return {
        "journey": result.journey,
        "feasible": result.feasible,
        "open_ended": result.open_ended,
        "present_kinds": list(result.present_kinds),
        "missing_kinds": list(result.missing_kinds),
        "missing_calibrations": list(result.missing_calibrations),
        "pickup_span": list(result.pickup_span) if result.pickup_span else None,
        "return_span": list(result.return_span) if result.return_span else None,
        "total_span": list(result.total_span) if result.total_span else None,
        "true_time_bounds": {
            k: list(v) for k, v in result.true_time_bounds.items()
        },
        "reason": result.reason,
    }


def _pair_row(pair) -> dict:
    return {
        "pair": pair.pair,
        "weight": pair.weight,
        "basis": pair.basis,
        "traditional": pair.traditional,
        "delivery": pair.delivery,
        "eligible": pair.eligible,
        "open_ended": pair.open_ended,
        "exclusion_reasons": pair.exclusion_reasons,
        "coverage_mismatches": {
            dim: {"traditional": v[0], "delivery": v[1]}
            for dim, v in pair.coverage_mismatches.items()
        },
        "pickup_saving": list(pair.pickup_saving) if pair.pickup_saving else None,
        "return_saving": list(pair.return_saving) if pair.return_saving else None,
        "total_saving": list(pair.total_saving) if pair.total_saving else None,
    }


def _result_row(result) -> dict:
    row = {
        "statement": result.statement,
        "passed": result.passed,
        "reasons": result.reasons,
        "coverage": result.coverage,
    }
    if isinstance(result, SavingsResult):
        row.update(
            {
                "type": SAVINGS_CLAIM,
                "threshold_minutes": result.threshold_minutes,
                "reliability": result.reliability,
                "confidence": result.confidence,
                "segment": result.segment,
                "eligible_pairs": result.eligible_pairs,
                "excluded_pairs": result.excluded_pairs,
                "distribution": result.distribution,
                "estimates": result.estimates,
                "missing_bounds": result.missing_bounds,
            }
        )
    elif isinstance(result, BufferResult):
        row.update(
            {
                "type": BUFFER_CLAIM,
                "buffer_minutes": result.buffer_minutes,
                "reliability": result.reliability,
                "confidence": result.confidence,
                "eligible_journeys": result.eligible_journeys,
                "excluded": result.excluded,
                "tail": result.tail,
                "share_estimate": result.share_estimate,
            }
        )
    return row


def run_candidate(
    data_dir: str,
    as_of: str,
    candidate_file: str,
    replicates: int,
    seed: int,
) -> dict:
    """评估编辑临时提交的候选文案，不改动 statements.json 原始资料。"""
    candidate = json.loads(Path(candidate_file).read_text(encoding="utf-8"))
    bundle = load_bundle(data_dir, as_of=as_of)
    feasibility = evaluate_all(bundle)
    pairs = build_pair_evidence(bundle, feasibility)

    if candidate["claim"] == SAVINGS_CLAIM:
        result = evaluate_savings_statement(
            bundle,
            pairs,
            candidate,
            segment=candidate.get("segment", "total"),
            scenario_filters=candidate.get("scenario_filters"),
            replicates=replicates,
            seed=seed,
        )
    elif candidate["claim"] == BUFFER_CLAIM:
        result = evaluate_buffer_statement(
            bundle, feasibility, candidate, pairs
        )
    else:
        raise ValueError(f"未知文案用途：{candidate['claim']}")

    return {
        "as_of": as_of,
        "candidate_file": str(Path(candidate_file).resolve()),
        "candidate": candidate,
        "result": _result_row(result),
    }


def run_evaluate(data_dir: str, as_of: str, replicates: int, seed: int) -> dict:
    bundle = load_bundle(data_dir, as_of=as_of)
    feasibility = evaluate_all(bundle)
    pairs = build_pair_evidence(bundle, feasibility)

    results = {}
    for statement in bundle.statements:
        if statement["claim"] == SAVINGS_CLAIM:
            results[statement["statement"]] = evaluate_savings_statement(
                bundle,
                pairs,
                statement,
                replicates=replicates,
                seed=seed,
            )
        elif statement["claim"] == BUFFER_CLAIM:
            results[statement["statement"]] = evaluate_buffer_statement(
                bundle, feasibility, statement, pairs
            )

    decisions = evaluate_placement(bundle, results)
    return {
        "as_of": as_of,
        "data_dir": str(Path(data_dir).resolve()),
        "suppressed_rows_after_cutoff": bundle.suppressed_rows,
        "journey_feasibility": [
            _feasibility_row(feasibility[j["journey"]])
            for j in bundle.journeys
        ],
        "pair_evidence": [_pair_row(p) for p in pairs],
        "statement_results": {
            sid: _result_row(result) for sid, result in results.items()
        },
        "placement_decisions": [d.as_dict() for d in decisions],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="时间文案配对证据工具")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default="data", help="资料目录")
    common.add_argument("--as-of", default="9999-12-31", help="评估截止日")
    common.add_argument("--out", help="输出 JSON 文件，默认打印到标准输出")
    common.add_argument("--replicates", type=int, default=10000)
    common.add_argument("--seed", type=int, default=71235)

    sub.add_parser("evaluate", parents=[common], help="评估全部文案与投放")
    sub.add_parser("pairs", parents=[common], help="只输出配对净节省证据")
    sub.add_parser("journeys", parents=[common], help="只输出逐旅程可行性")

    candidate = sub.add_parser(
        "candidate", parents=[common], help="评估编辑提交的候选文案 JSON"
    )
    candidate.add_argument(
        "--candidate-file", required=True, help="候选文案 JSON（模板见 examples/）"
    )

    review = sub.add_parser("review", help="对比更正前后的两份评估报告")
    review.add_argument("--before", required=True)
    review.add_argument("--after", required=True)
    review.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command in {"evaluate", "pairs", "journeys", "candidate"}:
        report = run_evaluate(
            args.data, args.as_of, args.replicates, args.seed
        )
        if args.command == "pairs":
            report = {"as_of": args.as_of, "pair_evidence": report["pair_evidence"]}
        elif args.command == "journeys":
            report = {
                "as_of": args.as_of,
                "journey_feasibility": report["journey_feasibility"],
            }
        elif args.command == "candidate":
            report = run_candidate(
                args.data,
                args.as_of,
                args.candidate_file,
                args.replicates,
                args.seed,
            )
    else:
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        after = json.loads(Path(args.after).read_text(encoding="utf-8"))

        def _rehydrate_results(payload: dict):
            results = {}
            for sid, row in payload["statement_results"].items():
                if row["type"] == SAVINGS_CLAIM:
                    results[sid] = SavingsResult(
                        statement=sid,
                        passed=row["passed"],
                        threshold_minutes=row["threshold_minutes"],
                        reliability=row["reliability"],
                        confidence=row["confidence"],
                        segment=row["segment"],
                        eligible_pairs=row["eligible_pairs"],
                        excluded_pairs=row.get("excluded_pairs", {}),
                        coverage=row.get("coverage", {}),
                        distribution=row.get("distribution", []),
                        estimates=row.get("estimates", {}),
                        missing_bounds=row.get("missing_bounds"),
                        reasons=row.get("reasons", []),
                    )
                else:
                    results[sid] = BufferResult(
                        statement=sid,
                        passed=row["passed"],
                        buffer_minutes=row["buffer_minutes"],
                        reliability=row["reliability"],
                        confidence=row["confidence"],
                        eligible_journeys=row.get("eligible_journeys", []),
                        excluded=row.get("excluded", {}),
                        coverage=row.get("coverage", {}),
                        tail=row.get("tail", {}),
                        share_estimate=row.get("share_estimate"),
                        reasons=row.get("reasons", []),
                    )
            return results

        from evidence_tool.publish import RouteDecision

        def _rehydrate_decisions(payload: dict):
            return [
                RouteDecision(
                    page=row["page"],
                    route=row["route"],
                    statement=row["statement"],
                    decision=row["decision"],
                    reach_areas=row["reach_areas"],
                    evidence_areas=row["evidence_areas"],
                    show_exceptions=row["show_exceptions"],
                    reasons=row["reasons"],
                    accepted_reference=row.get("accepted_reference"),
                )
                for row in payload["placement_decisions"]
            ]

        entries = review_after_correction(
            _rehydrate_results(before),
            _rehydrate_results(after),
            _rehydrate_decisions(before),
            _rehydrate_decisions(after),
        )
        report = {
            "before_as_of": before["as_of"],
            "after_as_of": after["as_of"],
            "correction_review": entries,
        }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
