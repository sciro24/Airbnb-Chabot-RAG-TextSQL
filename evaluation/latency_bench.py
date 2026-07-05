"""Benchmark latenza: p50/p95/p99 per fase della pipeline + effetto cache.

Riusa i timing per fase raccolti in `core.observability.METRICS`
(vector_search, rerank, generate, sql_exec) — stesso percorso codice dell'app.

    python -m evaluation.latency_bench --rag "appartamento pulito" --sql "prezzo medio per tipo stanza" --repeat 5
"""
from __future__ import annotations

import argparse
import json
import statistics as stats

from core.observability import METRICS


def percentiles(vals: list[float]) -> dict:
    if not vals:
        return {}
    s = sorted(vals)

    def pct(p: float) -> float:
        idx = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
        return round(s[idx], 1)

    return {
        "n": len(s),
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "mean": round(stats.fmean(s), 1),
        "max": round(max(s), 1),
    }


def run(rag_query: str | None, sql_query: str | None, repeat: int) -> dict:
    from core.rag_core import answer_rag
    from core.analytics_core import answer_analytics

    METRICS.reset()
    for _ in range(repeat):
        if rag_query:
            answer_rag(rag_query)
        if sql_query:
            answer_analytics(sql_query)

    snap = METRICS.snapshot()
    per_phase = {
        phase: percentiles(vals)
        for phase, vals in METRICS.phase_timings.items()
    }
    return {
        "repeat": repeat,
        "per_phase_ms": per_phase,
        "cache": {
            "hits": snap["cache_hits"],
            "misses": snap["cache_misses"],
            "hit_ratio": snap["cache_hit_ratio"],
        },
        "errors": snap["errors"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rag", default=None, help="query RAG da misurare")
    ap.add_argument("--sql", default=None, help="query analytics da misurare")
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()
    if not args.rag and not args.sql:
        args.rag = "appartamento pulito e tranquillo vicino al centro"
    print(json.dumps(run(args.rag, args.sql, args.repeat), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
