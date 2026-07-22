"""Qualità della generazione via LLM-as-judge (stesso endpoint Databricks).

Punteggi 1-5 per faithfulness (risposta ancorata al contesto) e relevance
(risposta pertinente alla domanda).

    python -m evaluation.generation_eval --query-set evaluation/query_set.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from core import llm_client
from core.rag_core import answer_rag

JUDGE_SYSTEM = (
    "Sei un valutatore rigoroso di sistemi RAG. Assegna due punteggi interi da 1 a 5:\n"
    "- faithfulness: quanto la risposta è supportata SOLO dal contesto fornito.\n"
    "- relevance: quanto la risposta risponde effettivamente alla domanda.\n"
    'Rispondi SOLO con JSON: {"faithfulness": X, "relevance": Y}'
)


def judge(query: str, answer: str, contexts: list[str]) -> dict:
    ctx = "\n---\n".join(contexts) if contexts else "(nessun contesto)"
    prompt = (
        f"Domanda:\n{query}\n\nContesto:\n{ctx}\n\nRisposta del sistema:\n{answer}\n\nJSON:"
    )
    # max_tokens alto: il giudice e' un reasoning model, con budget basso esaurisce il
    # ragionamento prima di emettere il JSON finale.
    raw = llm_client.generate(prompt, system=JUDGE_SYSTEM, temperature=0.0, max_tokens=2048)
    f = re.search(r'"faithfulness"\s*:\s*([1-5])', raw)
    r = re.search(r'"relevance"\s*:\s*([1-5])', raw)
    return {
        "faithfulness": int(f.group(1)) if f else None,
        "relevance": int(r.group(1)) if r else None,
        "raw": raw,
    }


def run(query_set_path: str) -> dict:
    data = json.loads(Path(query_set_path).read_text())
    rows, f_scores, r_scores = [], [], []
    for q in data["queries"]:
        res = answer_rag(q["query"])
        contexts = [c["chunk_text"] for c in res.contexts]
        scores = judge(q["query"], res.answer, contexts)
        rows.append({"id": q.get("id"), **{k: scores[k] for k in ("faithfulness", "relevance")}})
        if scores["faithfulness"]:
            f_scores.append(scores["faithfulness"])
        if scores["relevance"]:
            r_scores.append(scores["relevance"])

    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "per_query": rows,
        "avg_faithfulness": mean(f_scores),
        "avg_relevance": mean(r_scores),
        "n": len(rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-set", default="evaluation/query_set.json")
    args = ap.parse_args()
    print(json.dumps(run(args.query_set), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
