"""Routing dell'intento via LLM: conversational | rag | analytics.

Temperatura bassa, output JSON forzato, parsing regex. Fallback su euristica a
parole chiave se l'endpoint non risponde (routing anche offline).
"""
from __future__ import annotations

import json
import re

from core import llm_client
from core.config import Settings, get_settings
from core.observability import METRICS

INTENTS = ("conversational", "rag", "analytics")

_SYSTEM = (
    "Classifica l'intento della domanda utente in una di tre categorie:\n"
    "- conversational: saluti, meta-domande, chiacchiere non legate ai dati.\n"
    "- rag: opinioni/esperienze qualitative dalle recensioni (es. 'com'è il quartiere', "
    "'gli ospiti si lamentano del rumore?').\n"
    "- analytics: numeri/aggregazioni sui listing (prezzi medi, conteggi, min/max, per quartiere).\n"
    'Rispondi SOLO con JSON: {"intent": "<categoria>"}'
)

_ANALYTICS_HINTS = re.compile(
    r"\b(prezzo|prezzi|media|medio|quanti|quante|numero|conteggio|max|min|massimo|minimo|"
    r"average|price|count|how many|most expensive|cheapest|per quartiere|per zona|distribuzione)\b",
    re.IGNORECASE,
)
_RAG_HINTS = re.compile(
    r"\b(recension|opinion|esperienz|com'è|come è|consigli|rumore|pulizia|zona tranquilla|"
    r"review|clean|noisy|safe|neighborhood vibe|host)\b",
    re.IGNORECASE,
)


def _heuristic(query: str) -> str:
    if _ANALYTICS_HINTS.search(query):
        return "analytics"
    if _RAG_HINTS.search(query):
        return "rag"
    return "conversational"


def classify(query: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    try:
        # max_tokens alto: gpt-oss è un reasoning model, con budget basso tronca
        # il ragionamento prima di emettere il JSON finale.
        raw = llm_client.generate(
            f'Domanda: {query}\nJSON:',
            system=_SYSTEM,
            temperature=0.0,
            max_tokens=2048,
            settings=settings,
        )
        m = re.search(r'"intent"\s*:\s*"(\w+)"', raw)
        if m and m.group(1) in INTENTS:
            intent = m.group(1)
        else:
            # Ultima spiaggia: prova a caricare tutta la risposta come JSON.
            intent = json.loads(raw).get("intent", "")
            if intent not in INTENTS:
                intent = _heuristic(query)
    except Exception:
        METRICS.record_error("intent")
        intent = _heuristic(query)

    METRICS.record_intent(intent)
    return intent
