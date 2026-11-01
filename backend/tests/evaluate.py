"""Score recorded runs against evaluation_cases.json.

Usage:
  python backend/tests/evaluate.py --results backend/tests/evaluation_results.json

Each result object is keyed by case ID and may contain queried_sources,
retrieved_record_ids, citations (record IDs), latency_ms,
grounded (manual True/False/null), abstained, memory_write_without_consent,
and memory_retrieved. Missing observations remain unscored, never assumed true.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("evaluation_cases.json")


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    source_hits = source_total = evidence_hits = evidence_total = citation_valid = citation_total = 0
    grounded_values: list[bool] = []
    latencies: list[float] = []
    for case in cases:
        result = results.get(case["id"], {})
        queried = set(result.get("queried_sources", []))
        retrieved = set(result.get("retrieved_record_ids", []))
        cited = set(result.get("citations", []))
        expected = set(case["expected_record_ids"])
        needed = set(case["required_sources"])
        source_total += len(needed)
        source_hits += len(needed & queried)
        evidence_total += len(expected)
        evidence_hits += len(expected & retrieved)
        if case.get("citation_required"):
            citation_total += 1
            citation_valid += int(bool(cited) and cited <= retrieved and expected <= cited)
        grounded = result.get("grounded")
        if isinstance(grounded, bool):
            grounded_values.append(grounded)
        latency = result.get("latency_ms")
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))
        checks = {}
        checks["source_selection"] = needed <= queried
        checks["evidence_recall"] = expected <= retrieved
        if case.get("citation_required"):
            checks["citation_validity"] = bool(cited) and cited <= retrieved and expected <= cited
        if case.get("must_abstain"):
            checks["abstained"] = bool(result.get("abstained", False))
        action = case.get("memory_action")
        if action == "write_after_explicit_instruction":
            checks["memory_written"] = bool(result.get("memory_written", False))
            checks["no_unconsented_write"] = not bool(result.get("memory_write_without_consent", False))
        elif action == "retrieve_prior_consent":
            checks["memory_retrieved"] = bool(result.get("memory_retrieved", False))
        rows.append({"id": case["id"], "category": case["category"], "checks": checks,
                     "retrieved_expected": sorted(expected & retrieved), "missing_expected": sorted(expected - retrieved),
                     "grounded": grounded, "latency_ms": latency})
    manual_grounded = _ratio(sum(grounded_values), len(grounded_values)) if grounded_values else None
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    p95_latency = None
    if latencies:
        ordered = sorted(latencies)
        p95_latency = ordered[max(0, int(0.95 * len(ordered) + 0.999) - 1)]
    metrics = {
        "source_selection": {"score": _ratio(source_hits, source_total), "target": 0.85, "passed": source_hits / source_total >= 0.85 if source_total else None, "hits": source_hits, "total": source_total},
        "evidence_recall": {"score": _ratio(evidence_hits, evidence_total), "target": 0.80, "passed": evidence_hits / evidence_total >= 0.80 if evidence_total else None, "hits": evidence_hits, "total": evidence_total},
        "citation_validity": {"score": _ratio(citation_valid, citation_total), "target": 1.0, "passed": citation_valid == citation_total if citation_total else None, "valid": citation_valid, "total": citation_total},
        "groundedness_manual_sample": {"score": manual_grounded, "target": 0.90, "passed": manual_grounded >= 0.90 if manual_grounded is not None else None, "sample_size": len(grounded_values)},
        "latency_ms": {"average": avg_latency, "p95": p95_latency, "target_average_below": 8000, "passed": avg_latency < 8000 if avg_latency is not None else None, "sample_size": len(latencies)},
    }
    return {"metrics": metrics, "cases": rows,
            "representative_cases": [row for row in rows if row["id"] in {"E01", "E07", "E10", "E13", "E17"}]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path, help="JSON object keyed by evaluation case ID")
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON report")
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text())
    results = json.loads(args.results.read_text())
    report = evaluate(cases, results)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
