"""Entrypoint Streamlit multipagina (Chat + Osservabilità).

    streamlit run ui/app_streamlit.py

Importa core.* in-process; storage/vector/SQL/LLM sono su Databricks. Dati: solo Roma.
"""
from __future__ import annotations

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
        "Quanti host hanno più di 5 annunci?",
    ],
    "🔎 Recensioni (RAG)": [
        "Gli ospiti si lamentano del rumore?",
        "Cosa dicono le recensioni su pulizia e host?",
        "I quartieri centrali sono descritti come tranquilli?",
        "Le recensioni menzionano la vicinanza ai mezzi?",
    ],
}


# --------------------------------------------------------------- risorse ------
@st.cache_resource(show_spinner="Carico il reranker locale…")
def _load_reranker():
    from core.reranker import get_reranker
    return get_reranker()


@st.cache_data(ttl=600, show_spinner=False)
def _neighbourhoods() -> list[str]:
    """Quartieri disponibili (per il filtro RAG) letti da Databricks."""
    try:
        s = get_settings()
        _, rows = analytics_core._run_sql(
            s, f"SELECT DISTINCT neighbourhood_display FROM {s.analytics_table} "
               "WHERE neighbourhood_display IS NOT NULL ORDER BY 1")
        return [r[0] for r in rows]
    except Exception:
        return []


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
    """Espander con SQL/righe (analytics) o recensioni usate (RAG)."""
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


def process(query: str, neighbourhood: str | None) -> dict:
    """Esegue la pipeline con streaming live e ritorna il messaggio da salvare in history."""
    intent = intent_classifier.classify(query)
    st.caption(f"🧭 intent → **{intent}**")
    msg: dict = {"intent": intent}

    if intent == "analytics":
        ph = st.empty(); ph.markdown(DOTS_HTML, unsafe_allow_html=True)
        res, nl_prompt = analytics_core.prepare(query)
        ph.empty()
        answer = stream_answer(llm_client.generate_stream(nl_prompt, temperature=0.2))
        msg.update(answer=answer, sql=res.sql, row_count=res.row_count, preview=res.preview)
    elif intent == "rag":
        ph = st.empty(); ph.markdown(DOTS_HTML, unsafe_allow_html=True)
        contexts, prompt = rag_core.retrieve(query, neighbourhood=neighbourhood)
        ph.empty()
        answer = stream_answer(llm_client.generate_stream(
            prompt, system=rag_core.RAG_SYSTEM, temperature=0.3))
        msg.update(answer=answer, contexts=contexts)
    else:
        answer = stream_answer(llm_client.generate_stream(
            query, system="Sei l'assistente di un'app di analisi Airbnb su Roma. Rispondi breve "
            "e invita a fare domande sui dati (prezzi, quartieri, recensioni).", temperature=0.5))
        msg.update(answer=answer)

    render_details(msg)
    return msg


# ----------------------------------------------------------------- pagine -----
def page_chat() -> None:
    st.title("🏠 Airbnb RAG + Analytics — Roma")
    st.caption("Doppia pipeline: RAG sulle recensioni (Vector Search) · Text-to-SQL (SQL Warehouse).")

    # Filtro quartiere per il ramo RAG (aiuta chi non conosce le zone)
    nbhs = _neighbourhoods()
    sel = st.sidebar.selectbox("Filtro quartiere (RAG)", ["— tutti —"] + nbhs)
    neighbourhood = None if sel == "— tutti —" else sel

    # Domande suggerite (chip cliccabili)
    st.sidebar.markdown("**Domande di esempio**")
    for gruppo, domande in DOMANDE_ESEMPIO.items():
        with st.sidebar.expander(gruppo):
            for d in domande:
                if st.button(d, key=f"ex_{d}", use_container_width=True):
                    st.session_state.pending = d

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ridisegna la conversazione dallo stato
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                st.caption(f"🧭 intent → **{m['data']['intent']}**")
                st.markdown(m["data"]["answer"])
                render_details(m["data"])

    query = st.chat_input("Chiedi prezzi, quartieri, recensioni…") or st.session_state.pop("pending", None)
    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)
        with st.chat_message("assistant"):
            try:
                data = process(query, neighbourhood)
                st.session_state.messages.append({"role": "assistant", "data": data})
            except Exception as exc:
                st.error(f"Errore: {exc}")


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
    phases = snap["phases"]
    if phases:
        st.dataframe([{"fase": p, **v} for p, v in phases.items()], use_container_width=True)
    else:
        st.info("Nessuna richiesta ancora registrata.")

    if snap["errors"]:
        st.subheader("Errori")
        st.warning(snap["errors"])
    if st.button("Reset metriche"):
        METRICS.reset()
        st.rerun()


# ------------------------------------------------------------------ main ------
_load_reranker()  # precarica il reranker a startup
st.navigation([
    st.Page(page_chat, title="Chat", icon="💬", default=True),
    st.Page(page_observability, title="Osservabilità", icon="📊"),
]).run()
