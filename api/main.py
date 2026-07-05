"""App FastAPI: API (health, listings, geojson, chat SSE, metrics) + frontend statico.

    uvicorn api.main:app --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
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


def _chat_events(query: str, scope: dict | None):
    """Generatore SSE: evento `meta` con i metadati, poi `token`, poi `done`."""
    intent = intent_classifier.classify(query)

    if intent == "analytics":
        res, nl_prompt = analytics_core.prepare(query)
        yield _sse("meta", {"intent": intent, "sql": res.sql,
                            "row_count": res.row_count, "preview": res.preview})
        for chunk in llm_client.generate_stream(nl_prompt, system=analytics_core.NL_SYSTEM, temperature=0.2):
            yield _sse("token", {"text": chunk})

    elif intent == "rag":
        nbh = None
        if scope and scope.get("kind") == "neighbourhood":
            nbh = scope.get("neighbourhood")
        elif not scope:
            nbh = services.match_neighbourhood(query, services.neighbourhoods())

        if scope and scope.get("kind") == "listing":
            contexts, prompt = rag_core.retrieve(query, listing_id=int(scope["listing_id"]))
            yield _sse("meta", {"intent": intent, "contexts": _ctx_view(contexts)})
            if not contexts:
                yield _sse("token", {"text": "Non ci sono recensioni disponibili per questo alloggio."})
            else:
                for chunk in llm_client.generate_stream(prompt, system=rag_core.RAG_SYSTEM, temperature=0.3):
                    yield _sse("token", {"text": chunk})

        elif nbh:
            contexts, prompt = rag_core.retrieve(query, neighbourhood=nbh, top_k=40, rerank_k=8)
            yield _sse("meta", {"intent": intent, "contexts": _ctx_view(contexts), "neighbourhood": nbh})
            for chunk in llm_client.generate_stream(prompt, system=rag_core.RAG_SYSTEM_AGG, temperature=0.3):
                yield _sse("token", {"text": chunk})

        else:  # troppo generica: chiedi il quartiere
            yield _sse("meta", {"intent": intent, "clarify": True,
                                "neighbourhoods": services.neighbourhoods()})
            yield _sse("token", {"text": (
                "La domanda è ampia per un'intera città: le recensioni variano molto da zona a "
                "zona e da alloggio ad alloggio. Su quale **quartiere** vuoi concentrarti? "
                "(oppure scegli un annuncio dalla mappa)")})

    else:  # conversational
        yield _sse("meta", {"intent": intent})
        sys_p = ("Sei l'assistente di un'app di analisi Airbnb su Roma. Rispondi breve e invita "
                 "a fare domande sui dati (prezzi, quartieri, recensioni).")
        for chunk in llm_client.generate_stream(query, system=sys_p, temperature=0.5):
            yield _sse("token", {"text": chunk})

    yield _sse("done", {})


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    return StreamingResponse(_chat_events(req.query, req.scope), media_type="text/event-stream")


# --------------------------------------------------------- frontend statico ---
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
