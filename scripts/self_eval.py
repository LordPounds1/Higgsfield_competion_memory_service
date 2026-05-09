from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures" / "eval_fixture.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local recall quality fixture against a running service.")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--fail-under", type=float, default=0.75)
    args = parser.parse_args()

    report = run_fixture(args.base_url.rstrip("/"), args.fixture)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["composite_score"] >= args.fail_under else 1


def run_fixture(base_url: str, fixture_path: Path) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    expected_hits = 0
    expected_total = 0
    empty_hits = 0
    empty_total = 0
    latencies: list[float] = []

    for scenario in fixture["scenarios"]:
        cleanup_user(base_url, scenario["user_id"])
        for turn in scenario["turns"]:
            payload = {
                "session_id": turn["session_id"],
                "user_id": scenario["user_id"],
                "messages": turn["messages"],
                "timestamp": turn["timestamp"],
                "metadata": {"scenario": scenario["name"]},
            }
            response = requests.post(f"{base_url}/turns", json=payload, timeout=20)
            response.raise_for_status()

        for probe in scenario["probes"]:
            start = time.perf_counter()
            response = requests.post(
                f"{base_url}/recall",
                json={
                    "query": probe["query"],
                    "session_id": probe["session_id"],
                    "user_id": scenario["user_id"],
                    "max_tokens": 512,
                },
                timeout=10,
            )
            response.raise_for_status()
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)
            body = response.json()
            context = body.get("context", "")

            if probe["expected"] == "empty":
                passed = not context.strip() and not body.get("citations")
                empty_total += 1
                empty_hits += int(passed)
                probes.append(
                    {
                        "scenario": scenario["name"],
                        "query": probe["query"],
                        "passed": passed,
                        "expected": "empty",
                        "latency_ms": round(latency_ms, 2),
                    }
                )
                continue

            expected = list(probe["expected"])
            not_expected = list(probe.get("not_expected", []))
            hits = [item for item in expected if item.lower() in context.lower()]
            misses_bad_terms = [item for item in not_expected if item.lower() in context.lower()]
            expected_total += len(expected)
            expected_hits += len(hits)
            passed = len(hits) == len(expected) and not misses_bad_terms
            probes.append(
                {
                    "scenario": scenario["name"],
                    "query": probe["query"],
                    "passed": passed,
                    "expected": expected,
                    "hits": hits,
                    "not_expected_hits": misses_bad_terms,
                    "latency_ms": round(latency_ms, 2),
                }
            )

    recall_hit_rate = expected_hits / expected_total if expected_total else 1.0
    empty_precision = empty_hits / empty_total if empty_total else 1.0
    composite_score = round((0.85 * recall_hit_rate) + (0.15 * empty_precision), 4)
    return {
        "base_url": base_url,
        "fixture": str(fixture_path),
        "expected_hits": expected_hits,
        "expected_total": expected_total,
        "recall_hit_rate": round(recall_hit_rate, 4),
        "empty_hits": empty_hits,
        "empty_total": empty_total,
        "empty_precision": round(empty_precision, 4),
        "composite_score": composite_score,
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(percentile(latencies, 95), 2) if latencies else 0.0,
        "probes": probes,
    }


def cleanup_user(base_url: str, user_id: str) -> None:
    response = requests.delete(f"{base_url}/users/{user_id}", timeout=10)
    if response.status_code not in {204, 404}:
        response.raise_for_status()


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile_value / 100)
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main())
