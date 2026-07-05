"""Funzioni di supporto per gli endpoint: dati mappa, quartieri, health. Riusa core.*."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from core.analytics_core import _run_sql
from core.config import get_settings

ASSETS = Path(__file__).resolve().parent / "assets"

# Cache in-process con TTL (evita di ribattere il warehouse ad ogni richiesta).
_CACHE: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: int, fn):
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < ttl:
        return _CACHE[key][1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def neighbourhoods() -> list[str]:
    """Municipi disponibili."""
    def q():
        s = get_settings()
        _, rows = _run_sql(
            s, f"SELECT DISTINCT neighbourhood_display FROM {s.analytics_table} "
               "WHERE neighbourhood_display IS NOT NULL ORDER BY 1")
        return [r[0] for r in rows]
    return _cached("nbh", 600, q)


def listings_with_reviews() -> list[dict]:
    """Annunci che hanno recensioni nell'indice VS (+ coordinate) per la mappa."""
    def q():
        s = get_settings()
        gold = f"{s.uc_catalog}.{s.uc_schema}.gold_review_chunks"
        sql = (f"SELECT DISTINCT l.id, l.name, l.latitude, l.longitude, l.room_type, "
               f"l.price, l.neighbourhood_display FROM {s.analytics_table} l "
               f"JOIN (SELECT DISTINCT listing_id FROM {gold}) r ON l.id = r.listing_id "
               "WHERE l.latitude IS NOT NULL")
        cols = ["id", "name", "lat", "lon", "room_type", "price", "neighbourhood"]
        _, rows = _run_sql(s, sql)
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["id"] = int(d["id"])
            d["lat"] = float(d["lat"]); d["lon"] = float(d["lon"])
            d["price"] = float(d["price"]) if d["price"] is not None else None
            out.append(d)
        return out
    return _cached("listings", 600, q)


def geojson() -> dict:
    return json.loads((ASSETS / "rome_neighbourhoods.geojson").read_text())


def match_neighbourhood(query: str, nbhs: list[str]) -> str | None:
    """Trova un municipio citato nel testo (ignora il prefisso in numeri romani)."""
    q = query.lower()
    for n in nbhs:
        core_name = n.split(" ", 1)[-1].lower()
        if core_name and core_name in q:
            return n
    return None


import re

# Parole poco distintive da ignorare nel match del nome alloggio.
_STOP = {"room", "rooms", "apartment", "apt", "flat", "house", "home", "casa", "roma",
         "rome", "near", "the", "with", "and", "studio", "cozy", "central", "centro",
         "di", "del", "della", "alloggio", "appartamento", "stanza", "dicono", "prezzo",
         "dove", "trova", "cosa", "quale", "come", "info", "informazioni"}


def _sig_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zàèéìòùáéíóú0-9]+", s.lower()) if len(w) >= 3 and w not in _STOP}


def resolve_listing(query: str) -> dict | None:
    """Trova l'alloggio citato per nome nella domanda (match per parole significative)."""
    qw = _sig_words(query)
    if not qw:
        return None
    best, best_score = None, 0
    for l in listings_with_reviews():
        score = len(qw & _sig_words(l["name"]))
        if score > best_score:
            best, best_score = l, score
    return best if best_score >= 1 else None


def health(probe: bool = False) -> dict:
    """Stato configurazione + (se probe) test live di LLM/embedding/SQL."""
    s = get_settings()
    res = {
        "host": s.databricks_host,
        "llm_endpoint": s.llm_endpoint_name,
        "embedding_endpoint": s.embedding_endpoint_name,
        "vs_index": s.vs_index,
        "sql_warehouse": bool(s.sql_warehouse_id),
        "reranker_model": s.reranker_model,
    }
    if not probe:
        return res
    try:
        from core import llm_client
        llm_client.generate("ok", max_tokens=256)
        res["llm"] = "ok"
    except Exception as e:
        res["llm"] = f"errore: {str(e)[:100]}"
    try:
        url = s.endpoint_url(s.embedding_endpoint_name)
        r = requests.post(url, headers={"Authorization": f"Bearer {s.databricks_token}"},
                          json={"input": ["ping"]}, timeout=s.http_timeout_seconds)
        res["embedding"] = "ok" if r.ok else f"errore {r.status_code}"
    except Exception as e:
        res["embedding"] = f"errore: {str(e)[:100]}"
    try:
        _run_sql(s, "SELECT 1")
        res["sql"] = "ok"
    except Exception as e:
        res["sql"] = f"errore: {str(e)[:100]}"
    return res
