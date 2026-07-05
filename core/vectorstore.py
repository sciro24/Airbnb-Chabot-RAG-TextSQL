"""Client Databricks Vector Search (REST).

L'indice è Delta Sync con embedding calcolati da Databricks: la query si passa come
testo (`query_text`) e l'indice embedda con lo stesso modello — nessun embed locale.
"""
from __future__ import annotations

import json

import requests

from core.config import Settings, get_settings


def _query(settings: Settings, query_text: str, columns: list[str],
           num_results: int, filters: dict | None) -> list[dict]:
    url = f"{settings.api_base}/api/2.0/vector-search/indexes/{settings.vs_index}/query"
    payload: dict = {"query_text": query_text, "columns": columns, "num_results": num_results}
    if filters:
        payload["filters_json"] = json.dumps(filters)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {settings.databricks_token}"},
        json=payload,
        timeout=settings.http_timeout_seconds,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Vector Search query -> {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    cols = [c["name"] for c in data.get("manifest", {}).get("columns", [])]
    rows = data.get("result", {}).get("data_array", []) or []
    return [dict(zip(cols, r)) for r in rows]


# Colonne restituite dall'indice (metadati per filtri + testo per rerank/generazione)
COLUMNS = ["chunk_id", "listing_id", "neighbourhood", "room_type", "chunk_text"]


class VectorStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, query_text: str, top_k: int = 20, neighbourhood: str | None = None,
               listing_id: int | None = None) -> list[dict]:
        """Ricerca ibrida via Vector Search, con filtro opzionale per quartiere o annuncio."""
        filters: dict = {}
        if listing_id is not None:
            filters["listing_id"] = int(listing_id)
        if neighbourhood:
            filters["neighbourhood"] = neighbourhood.strip().lower()
        return _query(self.settings, query_text, COLUMNS, top_k, filters or None)


def get_vectorstore(settings: Settings | None = None) -> VectorStore:
    return VectorStore(settings or get_settings())
