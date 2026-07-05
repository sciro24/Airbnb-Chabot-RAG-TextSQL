"""Entrypoint Streamlit multipagina (Chat · Mappa · Osservabilità).

    streamlit run ui/app_streamlit.py

Importa core.* in-process; storage/vector/SQL/LLM sono su Databricks. Dati: solo Roma.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Rende importabile la repo root quando lanciato con `streamlit run ui/app_streamlit.py`.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core import analytics_core, intent_classifier, llm_client, rag_core  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.observability import METRICS  # noqa: E402

st.set_page_config(page_title="Airbnb RAG + Analytics — Roma", page_icon="🏠", layout="wide")

ASSETS = Path(__file__).resolve().parent / "assets"

# Dots rimbalzanti mostrati durante l'attesa pre-generazione (retrieval/SQL/reasoning).
DOTS_HTML = """
<style>
.dot-flash span{display:inline-block;width:9px;height:9px;margin:0 3px;border-radius:50%;
  background:#888;animation:dotflash 1s infinite ease-in-out both}
.dot-flash span:nth-child(2){animation-delay:.16s}
.dot-flash span:nth-child(3){animation-delay:.32s}
@keyframes dotflash{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-7px);opacity:1}}
</style>
<div class="dot-flash"><span></span><span></span><span></span></div>
"""

DOMANDE_ESEMPIO = {
    "📊 Analytics": [
        "Qual è il prezzo medio per tipo di stanza?",
        "Quali sono i 10 quartieri con più annunci?",
        "Qual è il quartiere più costoso in media?",
    ],
    "🔎 Recensioni (RAG)": [
        "Gli ospiti si lamentano del rumore?",
        "Cosa dicono le recensioni su pulizia e host?",
    ],
}

# Palette per colorare quartieri/punti (RGB).
PALETTE = [
    [230, 25, 75], [60, 180, 75], [0, 130, 200], [245, 130, 48], [145, 30, 180],
    [70, 240, 240], [240, 50, 230], [210, 245, 60], [250, 190, 190], [0, 128, 128],
    [230, 190, 255], [170, 110, 40], [128, 0, 0], [0, 0, 128], [128, 128, 0],
]


# --------------------------------------------------------------- risorse ------
@st.cache_resource(show_spinner="Carico il reranker locale…")
def _load_reranker():
    from core.reranker import get_reranker
    return get_reranker()


@st.cache_data(ttl=600, show_spinner=False)
def _neighbourhoods() -> list[str]:
    """Quartieri (municipi) disponibili, letti da Databricks."""
    try:
        s = get_settings()
        _, rows = analytics_core._run_sql(
            s, f"SELECT DISTINCT neighbourhood_display FROM {s.analytics_table} "
               "WHERE neighbourhood_display IS NOT NULL ORDER BY 1")
        return [r[0] for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner="Carico gli annunci…")
def _listings_geo() -> list[dict]:
    """Annunci con coordinate per la mappa (id, nome, lat/lon, prezzo, tipo, quartiere)."""
    s = get_settings()
    _, rows = analytics_core._run_sql(
        s, "SELECT id, name, latitude, longitude, room_type, price, neighbourhood_display "
           f"FROM {s.analytics_table} WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    cols = ["id", "name", "lat", "lon", "room_type", "price", "neighbourhood"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["lat"] = float(d["lat"]); d["lon"] = float(d["lon"])
        out.append(d)
    return out


@st.cache_data(show_spinner=False)
def _geojson() -> dict | None:
    f = ASSETS / "rome_neighbourhoods.geojson"
    return json.loads(f.read_text()) if f.exists() else None


def _color_map(names: list[str]) -> dict[str, list[int]]:
    return {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(sorted(names))}


def _match_neighbourhood(query: str, nbhs: list[str]) -> str | None:
    """Trova un quartiere citato nel testo (ignora il prefisso in numeri romani del municipio)."""
    q = query.lower()
    for n in nbhs:
        core_name = n.split(" ", 1)[-1].lower()  # "I Centro Storico" -> "centro storico"
        if core_name and core_name in q:
            return n
    return None


def stream_answer(gen) -> str:
    """Mostra i dots finché non arriva il primo token, poi streamma il testo. Ritorna il testo."""
    ph = st.empty()
    ph.markdown(DOTS_HTML, unsafe_allow_html=True)
    acc = ""
    for chunk in gen:
        if not acc:
            ph.empty()
        acc += chunk
        ph.markdown(acc + " ▌")
    ph.markdown(acc or "_(nessuna risposta)_")
    return acc


# --------------------------------------------------------------- rendering ----
def render_details(msg: dict) -> None:
    if msg["intent"] == "analytics" and msg.get("sql"):
        with st.expander(f"SQL eseguita · {msg['row_count']} righe"):
            st.code(msg["sql"], language="sql")
            if msg.get("preview"):
                st.dataframe(msg["preview"], use_container_width=True)
    elif msg["intent"] == "rag" and msg.get("contexts"):
        with st.expander(f"Recensioni usate ({len(msg['contexts'])})"):
            for c in msg["contexts"]:
                st.markdown(f"**{c.get('neighbourhood','?')}** "
                            f"(score {c.get('rerank_score', 0):.2f})\n\n> {c['chunk_text'][:400]}")


def _scope_label() -> str:
    sc = st.session_state.get("scope")
    if not sc:
        return "tutta Roma"
    return f"annuncio «{sc['label']}»" if sc["kind"] == "listing" else f"quartiere «{sc['neighbourhood']}»"


def process(query: str) -> dict:
    """Esegue la pipeline con streaming live e ritorna il messaggio da salvare in history."""
    intent = intent_classifier.classify(query)
    st.caption(f"🧭 intent → **{intent}**")
    msg: dict = {"intent": intent}
    scope = st.session_state.get("scope")

    if intent == "analytics":
        ph = st.empty(); ph.markdown(DOTS_HTML, unsafe_allow_html=True)
        res, nl_prompt = analytics_core.prepare(query)
        ph.empty()
        answer = stream_answer(llm_client.generate_stream(nl_prompt, temperature=0.2))
        msg.update(answer=answer, sql=res.sql, row_count=res.row_count, preview=res.preview)

    elif intent == "rag":
        # Determina lo scope: annuncio selezionato > quartiere (scope/testo) > generico
        nbh = None
        if scope and scope["kind"] == "neighbourhood":
            nbh = scope["neighbourhood"]
        elif not scope:
            nbh = _match_neighbourhood(query, _neighbourhoods())

        if scope and scope["kind"] == "listing":
            ph = st.empty(); ph.markdown(DOTS_HTML, unsafe_allow_html=True)
            contexts, prompt = rag_core.retrieve(query, listing_id=scope["listing_id"])
            ph.empty()
            if not contexts:
                answer = "Non ci sono recensioni disponibili per questo alloggio nell'indice."
                st.markdown(answer)
            else:
                answer = stream_answer(llm_client.generate_stream(
                    prompt, system=rag_core.RAG_SYSTEM, temperature=0.3))
            msg.update(answer=answer, contexts=contexts)

        elif nbh:
            # aggregato di quartiere: più recensioni per un quadro più ampio
            ph = st.empty(); ph.markdown(DOTS_HTML, unsafe_allow_html=True)
            contexts, prompt = rag_core.retrieve(query, neighbourhood=nbh, top_k=40, rerank_k=8)
            ph.empty()
            answer = stream_answer(llm_client.generate_stream(
                prompt, system=rag_core.RAG_SYSTEM_AGG, temperature=0.3))
            msg.update(answer=answer, contexts=contexts, neighbourhood=nbh)

        else:
            # domanda troppo generica per tutta Roma: chiedi il quartiere
            answer = ("La domanda è ampia per un'intera città: le recensioni variano molto da "
                      "zona a zona e da alloggio ad alloggio. Su quale **quartiere** vuoi "
                      "concentrarti? (o scegli un annuncio dalla pagina **Mappa**)")
            st.markdown(answer)
            msg.update(answer=answer, clarify=True, query=query)

    else:
        answer = stream_answer(llm_client.generate_stream(
            query, system="Sei l'assistente di un'app di analisi Airbnb su Roma. Rispondi breve "
            "e invita a fare domande sui dati (prezzi, quartieri, recensioni).", temperature=0.5))
        msg.update(answer=answer)

    render_details(msg)
    return msg


# ----------------------------------------------------------------- pagine -----
def _sidebar_scope() -> None:
    """Mostra lo scope attivo + filtro quartiere + domande di esempio."""
    st.sidebar.markdown(f"**Ambito RAG:** {_scope_label()}")
    if st.session_state.get("scope") and st.sidebar.button("✖ Rimuovi ambito"):
        st.session_state.scope = None
        st.rerun()

    nbhs = _neighbourhoods()
    cur = st.session_state.get("scope")
    idx = (nbhs.index(cur["neighbourhood"]) + 1) if cur and cur["kind"] == "neighbourhood" and cur["neighbourhood"] in nbhs else 0
    sel = st.sidebar.selectbox("Filtro quartiere (RAG)", ["— tutti —"] + nbhs, index=idx)
    if sel != "— tutti —" and (not cur or cur.get("neighbourhood") != sel):
        st.session_state.scope = {"kind": "neighbourhood", "neighbourhood": sel}

    st.sidebar.markdown("**Domande di esempio**")
    for gruppo, domande in DOMANDE_ESEMPIO.items():
        with st.sidebar.expander(gruppo):
            for d in domande:
                if st.button(d, key=f"ex_{d}", use_container_width=True):
                    st.session_state.pending = d


def page_chat() -> None:
    _load_reranker()  # torch caricato solo qui, non nella pagina Osservabilità
    st.title("🏠 Airbnb RAG + Analytics — Roma")
    st.caption("Doppia pipeline: RAG sulle recensioni (Vector Search) · Text-to-SQL (SQL Warehouse).")
    _sidebar_scope()

    st.session_state.setdefault("messages", [])
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                st.caption(f"🧭 intent → **{m['data']['intent']}**")
                st.markdown(m["data"]["answer"])
                render_details(m["data"])

    # bottoni-quartiere sotto l'ultima richiesta di chiarimento
    last = st.session_state.messages[-1] if st.session_state.messages else None
    if last and last["role"] == "assistant" and last["data"].get("clarify"):
        st.write("Scegli un quartiere:")
        cols = st.columns(3)
        for i, n in enumerate(_neighbourhoods()):
            if cols[i % 3].button(n, key=f"clar_{n}"):
                st.session_state.scope = {"kind": "neighbourhood", "neighbourhood": n}
                st.session_state.pending = last["data"]["query"]
                st.rerun()

    query = st.chat_input("Chiedi prezzi, quartieri, recensioni…") or st.session_state.pop("pending", None)
    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)
        with st.chat_message("assistant"):
            try:
                data = process(query)
                st.session_state.messages.append({"role": "assistant", "data": data})
            except Exception as exc:
                st.error(f"Errore: {exc}")
        st.rerun()  # ridisegna per mostrare eventuali bottoni di chiarimento


def page_map() -> None:
    import pydeck as pdk
    st.title("🗺️ Mappa di Roma — annunci per quartiere")
    st.caption("Punti = annunci. Clicca un punto per interrogare il chatbot su quello specifico alloggio.")

    listings = _listings_geo()
    nbhs = sorted({d["neighbourhood"] for d in listings if d["neighbourhood"]})
    colors = _color_map(nbhs)

    chosen = st.multiselect("Filtra quartieri", nbhs, default=[])
    pts = [d for d in listings if (not chosen or d["neighbourhood"] in chosen)]
    for d in pts:
        d["color"] = colors.get(d["neighbourhood"], [150, 150, 150])
    st.caption(f"{len(pts)} annunci mostrati")

    layers = []
    gj = _geojson()
    if gj:  # confini reali dei municipi
        for feat in gj["features"]:
            feat["properties"]["fill"] = colors.get(feat["properties"].get("neighbourhood"), [150, 150, 150])
        layers.append(pdk.Layer(
            "GeoJsonLayer", gj, stroked=True, filled=True, get_fill_color="properties.fill",
            get_line_color=[255, 255, 255], line_width_min_pixels=1, opacity=0.12, pickable=False))
    scatter = pdk.Layer(
        "ScatterplotLayer", pts, id="listings", get_position="[lon, lat]",
        get_fill_color="color", get_radius=40, pickable=True, auto_highlight=True)
    layers.append(scatter)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=41.9, longitude=12.5, zoom=10.5),
        map_style=None,
        tooltip={"text": "{name}\n{neighbourhood} · {room_type} · {price}€"})

    ev = st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key="map")

    picked = None
    try:
        objs = ev.selection["objects"].get("listings", [])
        picked = objs[0] if objs else None
    except Exception:
        picked = None

    if picked:
        st.success(f"Selezionato: **{picked.get('name','?')}** · {picked.get('neighbourhood','?')} "
                   f"· {picked.get('room_type','?')} · {picked.get('price','?')}€")
        if st.button("💬 Chiedi al chatbot su questo annuncio"):
            st.session_state.scope = {"kind": "listing", "listing_id": int(picked["id"]),
                                      "label": picked.get("name", str(picked["id"]))}
            st.session_state.pending = "Cosa dicono gli ospiti di questo alloggio?"
            st.switch_page(PAGES["chat"])


def page_observability() -> None:
    st.title("📊 Osservabilità & Metriche")
    settings = get_settings()
    c1, c2, c3 = st.columns(3)
    c1.metric("Databricks", "🟢" if settings.databricks_host else "🔴")
    c2.metric("SQL Warehouse", "🟢" if settings.sql_warehouse_id else "🔴")
    c3.caption(f"Vector Search index:\n`{settings.vs_index}`")

    snap = METRICS.snapshot()
    st.subheader("Richieste")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Intent totali", sum(snap["intent_counts"].values()))
    d2.metric("Cache hit", snap["cache_hits"])
    d3.metric("Cache miss", snap["cache_misses"])
    d4.metric("Hit ratio", f"{snap['cache_hit_ratio']:.0%}")
    if snap["intent_counts"]:
        st.bar_chart(snap["intent_counts"])

    st.subheader("Latenza per fase (ms)")
    if snap["phases"]:
        st.dataframe([{"fase": p, **v} for p, v in snap["phases"].items()], use_container_width=True)
    else:
        st.info("Nessuna richiesta ancora registrata.")

    if snap["errors"]:
        st.subheader("Errori"); st.warning(snap["errors"])
    if st.button("Reset metriche"):
        METRICS.reset(); st.rerun()


# ------------------------------------------------------------------ main ------
PAGES = {
    "chat": st.Page(page_chat, title="Chat", icon="💬", default=True),
    "map": st.Page(page_map, title="Mappa", icon="🗺️"),
    "obs": st.Page(page_observability, title="Osservabilità", icon="📊"),
}
st.navigation(list(PAGES.values())).run()
