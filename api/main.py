"""App FastAPI: API (health, listings, geojson, chat SSE, metrics) + frontend statico.

    uvicorn api.main:app --port 8000
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import services
from core import analytics_core, intent_classifier, llm_client, rag_core
from core.observability import METRICS

app = FastAPI(title="Airbnb RAG + Analytics — Roma")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"


@app.on_event("startup")
def _preload():
    # Precarica il reranker (torch) a startup, così la prima query RAG non è lenta.
    try:
        from core.reranker import get_reranker
        get_reranker()
    except Exception:
        pass


# ------------------------------------------------------------------ modelli ---
class ChatRequest(BaseModel):
    query: str
    scope: dict | None = None  # None | {"kind":"listing","listing_id":int} | {"kind":"neighbourhood","neighbourhood":str}


# ------------------------------------------------------------------ API --------
@app.get("/api/health")
def api_health(probe: bool = False):
    return services.health(probe=probe)


@app.get("/api/listings")
def api_listings():
    return services.listings_with_reviews()


@app.get("/api/neighbourhoods")
def api_neighbourhoods():
    return services.neighbourhoods()


@app.get("/api/neighbourhoods.geojson")
def api_geojson():
    return JSONResponse(services.geojson())


@app.get("/api/metrics")
def api_metrics():
    return METRICS.snapshot()


@app.post("/api/metrics/reset")
def api_metrics_reset():
    METRICS.reset()
    return {"ok": True}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _ctx_view(contexts: list[dict]) -> list[dict]:
    return [{"neighbourhood": c.get("neighbourhood"), "score": round(c.get("rerank_score", 0), 2),
             "text": c.get("chunk_text", "")[:400]} for c in contexts]


CONV_SYSTEM = ("Sei l'assistente di un'app di analisi Airbnb su Roma. Rispondi breve e invita "
               "a fare domande sui dati (prezzi, quartieri, recensioni).")

# Parole chiave analitiche (numeri/prezzi): con ambito attivo mantengono l'intent analytics.
_ANALYTICS_KW = re.compile(
    r"prezz|medi|quant|numero|conteggio|massim|minim|percentu|costo|economic|caro|"
    r"disponibil|notti|recension.*(quant|numero)|più caro|più costoso", re.IGNORECASE)


def _plan(query: str, scope: dict | None):
    """Instrada la domanda. Ritorna (meta_dict, iteratore di chunk di testo)."""
    intent = intent_classifier.classify(query)
    # Con un ambito attivo (annuncio/quartiere), a meno di parole chiave numeriche/di prezzo,
    # la domanda riguarda le recensioni di quel contesto -> RAG.
    if scope and intent != "rag" and not _ANALYTICS_KW.search(query):
        intent = "rag"

    if intent == "analytics":
        res, nl_prompt = analytics_core.prepare(query)
        meta = {"intent": intent, "sql": res.sql, "row_count": res.row_count, "preview": res.preview}
        return meta, llm_client.generate_stream(nl_prompt, system=analytics_core.NL_SYSTEM, temperature=0.2)

    if intent == "rag":
        # Priorità ambito: scope esplicito > quartiere citato > alloggio citato per nome.
        listing = None
        nbh = None
        if scope and scope.get("kind") == "listing":
            listing = {"id": int(scope["listing_id"]), "name": scope.get("label")}
        elif scope and scope.get("kind") == "neighbourhood":
            nbh = scope.get("neighbourhood")
        else:
            # nessuno scope: prima un quartiere citato (anche 'ostia'), poi un nome alloggio
            nbh = services.match_neighbourhood(query, services.neighbourhoods())
            if not nbh:
                m = services.resolve_listing(query)
                if m:
                    listing = {"id": m["id"], "name": m["name"]}

        if listing:
            contexts, prompt = rag_core.retrieve(query, listing_id=listing["id"], listing_name=listing["name"])
            meta = {"intent": intent, "contexts": _ctx_view(contexts), "listing": listing["name"]}
            if not contexts:
                return meta, iter([f"Non ci sono recensioni disponibili per «{listing['name']}»."])
            return meta, llm_client.generate_stream(prompt, system=rag_core.RAG_SYSTEM_LISTING, temperature=0.3)

        if nbh:
            contexts, prompt = rag_core.retrieve(query, neighbourhood=nbh, top_k=40, rerank_k=8)
            meta = {"intent": intent, "contexts": _ctx_view(contexts), "neighbourhood": nbh}
            return meta, llm_client.generate_stream(prompt, system=rag_core.RAG_SYSTEM_AGG, temperature=0.3)

        # troppo generica: chiedi il quartiere
        meta = {"intent": intent, "clarify": True, "neighbourhoods": services.neighbourhoods()}
        return meta, iter([
            "La domanda è ampia per un'intera città: le recensioni variano molto da zona a zona e "
            "da alloggio ad alloggio. Su quale **quartiere** vuoi concentrarti? "
            "(oppure scegli un annuncio dalla mappa)"])

    return {"intent": intent}, llm_client.generate_stream(query, system=CONV_SYSTEM, temperature=0.5)


# Cache risposte per (query, scope): domande ripetute non ricalcolano. Cap con eviction FIFO.
_RESP_CACHE: dict[str, dict] = {}
_CACHE_MAX = 300


def _chat_events(query: str, scope: dict | None):
    """Generatore SSE: `meta`, poi `token`, poi `done`. Con cache su (query, scope)."""
    key = query.strip().lower() + "|" + json.dumps(scope, sort_keys=True)
    cached = _RESP_CACHE.get(key)
    if cached is not None:
        METRICS.record_cache(True)
        yield _sse("meta", {**cached["meta"], "cached": True})
        yield _sse("token", {"text": cached["answer"]})
        yield _sse("done", {})
        return

    METRICS.record_cache(False)
    answer, meta = "", None
    try:
        meta, tokens = _plan(query, scope)
        yield _sse("meta", meta)
        for chunk in tokens:
            answer += chunk
            yield _sse("token", {"text": chunk})
    except Exception as exc:  # nessun errore deve interrompere lo stream a metà
        METRICS.record_error("chat")
        if meta is None:
            yield _sse("meta", {"intent": "error"})
        yield _sse("token", {"text": "Non riesco a rispondere a questa domanda. Prova a riformularla."})
        yield _sse("done", {})
        return
    _RESP_CACHE[key] = {"meta": meta, "answer": answer}
    if len(_RESP_CACHE) > _CACHE_MAX:  # eviction FIFO (dict mantiene ordine inserimento)
        _RESP_CACHE.pop(next(iter(_RESP_CACHE)))
    yield _sse("done", {})


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    return StreamingResponse(_chat_events(req.query, req.scope), media_type="text/event-stream")


# --------------------------------------------------------- frontend statico ---
# SPA fallback: gli asset sono serviti da /assets; ogni altra route (es. /metrics,
# refresh incluso) restituisce index.html così il router React gestisce la pagina.
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        f = DIST / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
