"""Metriche retrieval su Databricks Vector Search: Recall@k, MRR, nDCG.

La rilevanza è a livello di listing_id: un chunk recuperato conta come rilevante se
il suo `listing_id` è tra i `relevant_listing_ids` della query.

    python -m evaluation.retrieval_eval --query-set evaluation/query_set.json --k 5
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from core.config import get_settings
from core.vectorstore import get_vectorstore


def _rel(hit: dict, relevant: set[int]) -> int:
    try:
        return int(int(hit.get("listing_id")) in relevant)
    except (TypeError, ValueError):
        return 0


def recall_at_k(hits: list[dict], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    found = {int(h["listing_id"]) for h in hits[:k] if _rel(h, relevant)}
    return len(found) / len(relevant)


def mrr(hits: list[dict], relevant: set[int]) -> float:
    for i, h in enumerate(hits, 1):
        if _rel(h, relevant):
            return 1.0 / i
    return 0.0


def ndcg_at_k(hits: list[dict], relevant: set[int], k: int) -> float:
    dcg = sum(_rel(h, relevant) / math.log2(i + 1) for i, h in enumerate(hits[:k], 1))
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def run(query_set_path: str, k: int = 5, top_k: int = 20) -> dict:
    data = json.loads(Path(query_set_path).read_text())
    vs = get_vectorstore(get_settings())
    recalls, mrrs, ndcgs = [], [], []
    for q in data["queries"]:
        relevant = set(q.get("relevant_listing_ids", []))
        if not relevant:
            continue
        hits = vs.search(q["query"], top_k=top_k)
        recalls.append(recall_at_k(hits, relevant, k))
        mrrs.append(mrr(hits, relevant))
        ndcgs.append(ndcg_at_k(hits, relevant, k))

    def mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {f"recall@{k}": mean(recalls), "mrr": mean(mrrs),
            f"ndcg@{k}": mean(ndcgs), "n_queries": len(recalls)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-set", default="evaluation/query_set.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()
    print(json.dumps(run(args.query_set, args.k, args.top_k), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
