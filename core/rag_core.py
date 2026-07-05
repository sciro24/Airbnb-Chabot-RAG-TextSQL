"""Ramo RAG: retrieval (Databricks Vector Search) -> rerank locale -> generazione.

Vector Search fa la ricerca ibrida (vettoriale + testo) lato Databricks e restituisce
i chunk già ordinati; il CrossEncoder locale raffina i top-k prima della generazione.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core import llm_client
from core.config import Settings, get_settings
from core.observability import METRICS
from core.reranker import get_reranker
from core.vectorstore import get_vectorstore

RAG_SYSTEM = (
    "Sei un assistente che risponde SOLO usando le recensioni Airbnb fornite come contesto. "
    "Se il contesto non contiene la risposta, dillo esplicitamente. Cita gli aspetti concreti "
    "menzionati dagli ospiti. Rispondi nella lingua della domanda."
)


@dataclass
class RagResult:
    answer: str
    contexts: list[dict] = field(default_factory=list)


def build_prompt(query: str, contexts: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(contexts, 1):
        meta = f"[{c.get('neighbourhood','?')} / {c.get('room_type','?')}]"
        blocks.append(f"### Recensione {i} {meta}\n{c['chunk_text']}")
    context_str = "\n\n".join(blocks) if blocks else "(nessun contesto recuperato)"
    return (
        f"Contesto (recensioni recuperate):\n\n{context_str}\n\n"
        f"Domanda: {query}\n\nRisposta grounded sul contesto:"
    )


def retrieve(query: str, neighbourhood: str | None = None,
             settings: Settings | None = None) -> tuple[list[dict], str]:
    """Retrieval VS + rerank locale. Ritorna (contesti, prompt) pronto per la generazione."""
    settings = settings or get_settings()
    with METRICS.timer("vector_search"):
        hits = get_vectorstore(settings).search(
            query, top_k=settings.retrieval_top_k, neighbourhood=neighbourhood)
    with METRICS.timer("rerank"):
        reranked = get_reranker(settings).rerank(query, hits, top_k=settings.rerank_top_k)
    return reranked, build_prompt(query, reranked)


def answer_rag(query: str, neighbourhood: str | None = None,
               settings: Settings | None = None) -> RagResult:
    settings = settings or get_settings()
    contexts, prompt = retrieve(query, neighbourhood, settings)
    answer = llm_client.generate(prompt, system=RAG_SYSTEM, temperature=0.3, settings=settings)
    return RagResult(answer=answer, contexts=contexts)
