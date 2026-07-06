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


_NBH_SHORT_OK = {"eur"}  # nomi brevi di municipio comunque validi


def match_neighbourhood(query: str, nbhs: list[str]) -> str | None:
    """Trova un municipio citato: matcha una parola-chiave del nome (es. 'ostia' -> 'X Ostia/Acilia')."""
    q = set(re.findall(r"[a-zàèéìòùáéíóú]+", query.lower()))
    for n in nbhs:
        # scompone "X Ostia/Acilia" -> [x, ostia, acilia]; tiene i token distintivi
        toks = [t for t in re.split(r"[ /]", n.lower()) if len(t) >= 4 or t in _NBH_SHORT_OK]
        toks = [t for t in toks if t != "san"]  # troppo generico da solo
        if any(t in q for t in toks):
            return n
    return None


import re

# Parole comuni da ignorare quando si valuta se un n-gram è "distintivo".
_STOP = {"a", "e", "i", "o", "il", "la", "le", "lo", "gli", "un", "una", "uno", "di", "del",
         "della", "dei", "delle", "con", "per", "in", "su", "da", "che", "non", "si", "ci",
         "al", "alla", "the", "and", "with", "of", "in", "near", "room", "rooms", "apartment",
         "apt", "flat", "house", "home", "casa", "roma", "rome", "studio", "cozy", "b&b",
         "alloggio", "appartamento", "stanza", "cosa", "dove", "prezzo", "trova", "dicono",
         "villa", "suite", "loft", "attico", "residenza", "residence", "palazzo", "guesthouse",
         "camera", "monolocale", "bilocale", "dell", "sull", "che", "come"}


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9àèéìòùáéíóú&]+", s.lower()) if w]


def resolve_listing(query: str) -> dict | None:
    """Trova l'alloggio citato per NOME: un n-gram (>=2 parole, non tutto comune) del nome
    dev'essere presente come sottostringa nella domanda. Evita falsi positivi su parole comuni."""
    q = " " + " ".join(_tokens(query)) + " "
    best, best_len = None, 0
    for l in listings_with_reviews():
        words = _tokens(l["name"])
        for n in (5, 4, 3, 2):  # dal più lungo al più corto
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if all(w in _STOP for w in gram):
                    continue  # n-gram tutto parole comuni -> non distintivo
                phrase = " ".join(gram)
                if f" {phrase} " in q and len(phrase) > best_len:
                    best, best_len = l, len(phrase)
    return best


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
