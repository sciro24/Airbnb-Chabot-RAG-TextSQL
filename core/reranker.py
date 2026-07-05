"""Reranker CrossEncoder locale (mmarco-mMiniLMv2), device MPS. ~250MB RAM.

Caricato una volta (singleton); la UI lo avvolge in `@st.cache_resource`.
"""
from __future__ import annotations

from core.config import Settings, get_settings


class Reranker:
    def __init__(self, model_name: str, device: str):
        # Import pigro: non trascinare torch al semplice import del modulo.
        from sentence_transformers import CrossEncoder

        try:
            self.model = CrossEncoder(model_name, device=device, max_length=512)
            self.device = device
        except Exception:
            # MPS/GPU non disponibile -> fallback su CPU invece di crashare.
            self.model = CrossEncoder(model_name, device="cpu", max_length=512)
            self.device = "cpu"

    def rerank(
        self, query: str, hits: list[dict], top_k: int = 3, text_key: str = "chunk_text"
    ) -> list[dict]:
        """Scora le coppie (query, chunk_text), ritorna i top_k con `rerank_score`."""
        if not hits:
            return []
        pairs = [(query, h[text_key]) for h in hits]
        scores = self.model.predict(pairs, convert_to_numpy=True)
        for h, s in zip(hits, scores):
            h["rerank_score"] = float(s)
        ranked = sorted(hits, key=lambda h: h["rerank_score"], reverse=True)
        return ranked[:top_k]


# Singleton per (model, device) — Settings non è hashable, quindi niente lru_cache.
_RERANKER_CACHE: dict[tuple[str, str], Reranker] = {}


def get_reranker(settings: Settings | None = None) -> Reranker:
    settings = settings or get_settings()
    key = (settings.reranker_model, settings.reranker_device)
    if key not in _RERANKER_CACHE:
        _RERANKER_CACHE[key] = Reranker(*key)
    return _RERANKER_CACHE[key]
