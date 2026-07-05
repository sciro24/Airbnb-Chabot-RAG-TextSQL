# Airbnb RAG + Analytics — Databricks-native (Roma)

Sistema **RAG + Text-to-SQL** su dati Inside Airbnb di **Roma**. Storage, vettori e analytics
vivono su **Databricks**; una **web app React** parla col sistema tramite un backend **FastAPI**.

Doppia pipeline (analisi grounded, non solo QA documentale):

- **RAG** sulle recensioni: Databricks **Vector Search** (ricerca ibrida) → rerank locale → generazione.
- **Text-to-SQL** sui listing: NL → SQL (SELECT-only) → **SQL Warehouse** → risposta NL.

Un `intent_classifier` LLM instrada ogni domanda su `conversational | rag | analytics`.

---

## Architettura

```
UC Volume  workspace.airbnb.raw/rome/{listings,neighbourhoods,reviews.csv.gz}
   │  notebook Spark su Databricks (databricks/)
   ▼
Delta UC:  bronze_* → silver_* → gold_review_chunks   +  vista listings_enriched
   │                                   │
   ▼ Vector Search (Delta Sync)        ▼ SQL Warehouse
   review_chunks_index                 listings_enriched
                    ▲                     ▲
   FastAPI (api/) ──┴─────────────────────┘  importa core.* in-process
     │  intent → rag_core | analytics_core → LLM endpoint (streaming SSE)
     ▼
   web/ (React + Vite + Leaflet)  — build servito da FastAPI
```

| Livello | Tecnologia |
|---|---|
| ETL batch | notebook Spark su Databricks (serverless) |
| Storage | Unity Catalog (Delta tables, Volume per i raw) |
| Retrieval | Databricks Vector Search (Delta Sync, embedding lato Databricks) |
| Analytics | Databricks SQL Warehouse (Statement Execution API) |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (locale, MPS) |
| LLM + embedding | Databricks serving endpoint |
| Backend | FastAPI (API REST + SSE streaming), serve il frontend statico |
| Frontend | React + Vite + Leaflet (mappa) |
| Config | `.env` + pydantic-settings |

---

## Struttura repo

```
databricks/   notebook ETL (girano su Databricks)
  01_ingest_clean.py   raw Volume -> bronze/silver Delta (campiona N rec/annuncio via widget)
  02_chunk.py          silver_reviews -> gold_review_chunks (CDF on, per Vector Search)
  03_analytics.py      vista listings_enriched (join listings⋈neighbourhoods)
  04_vector_index.py   endpoint Vector Search + indice Delta Sync
core/         librerie in-process: config, llm_client (streaming), intent_classifier,
              reranker (locale), vectorstore (Vector Search), analytics_core (SQL), rag_core, observability
api/          backend FastAPI: main.py (route + SSE), services.py, assets/rome_neighbourhoods.geojson
web/          frontend React+Vite: pagine Home (mappa+chat) e Osservabilità
scripts/      check_databricks.py (verifica workspace)
evaluation/   retrieval (VS), generation (LLM-judge), latency
```

---

## Setup

```bash
# backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # compila HOST, TOKEN, SQL_WAREHOUSE_ID

# frontend
cd web && npm install && cd ..
```

## Collegamento Databricks (CLI)

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com --profile trial
databricks tokens create --comment airbnb-rag -p trial   # -> DATABRICKS_TOKEN in .env
python -m scripts.check_databricks                        # verifica endpoint + crediti
```

## Pipeline ETL (su Databricks)

```bash
# dati raw -> Volume UC
databricks fs mkdir dbfs:/Volumes/workspace/airbnb/raw/rome -p trial
databricks fs cp data/raw/rome/listings.csv        dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/neighbourhoods.csv  dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/reviews.csv.gz      dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
# notebook -> workspace
databricks workspace import-dir databricks /Workspace/Users/<you>/airbnb-rag --overwrite -p trial
```

Ordine: `01_ingest_clean` → `02_chunk` → `03_analytics` → `04_vector_index`.
I widget di `01` (`reviews_per_listing`, `max_listings`) scelgono quante recensioni e quanti
annunci coprire (campionamento distribuito, non i primi id).

## Avvio web app

```bash
# produzione (mono-processo): build React servito da FastAPI
cd web && npm run build && cd ..
uvicorn api.main:app --port 8000        # apri http://localhost:8000

# sviluppo: due processi (hot-reload)
uvicorn api.main:app --port 8000        # backend
cd web && npm run dev                   # frontend su :5173 (proxy /api -> :8000)
```

- **Home**: intro + mappa di Roma (municipi + annunci con recensioni) a sinistra, chat a destra.
  Click su un annuncio → chat sull'alloggio specifico; domanda generica → il bot chiede il quartiere;
  scope quartiere → RAG aggregato (più recensioni, con avviso che varia per alloggio). Risposte in streaming.
- **Osservabilità**: stato endpoint, latenza per fase, contatori intent/cache, info tecniche.

## Valutazione

```bash
python -m evaluation.retrieval_eval  --query-set evaluation/query_set.json --k 5
python -m evaluation.generation_eval --query-set evaluation/query_set.json
python -m evaluation.latency_bench   --rag "appartamento pulito" --sql "prezzo medio per tipo stanza"
```

---

## Scope dati / costi

Progetto ristretto a **Roma**. `01` campiona **N recensioni per annuncio** sui **M annunci** più
recensiti (default 6 × 2000 ≈ 12k chunk) così la mappa mostra ~2000 alloggi invece di pochi.
L'endpoint embedding pay-per-token embedda a ~2 righe/sec via Vector Search (il re-sync dell'indice
richiede tempo); l'endpoint Vector Search ha un costo *standing* finché attivo
(`databricks vector-search-endpoints delete-endpoint airbnb-vs` per spegnerlo).

## Sicurezza

La SQL generata dal LLM è non fidata: `analytics_core.validate_and_sanitize` impone
whitelist **SELECT/WITH-only** (no DDL/DML, statement singolo). Token solo in `.env` (gitignored).
