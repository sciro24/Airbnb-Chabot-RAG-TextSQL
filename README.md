# Airbnb RAG + Analytics — Databricks-native (Roma)

Sistema **RAG + Text-to-SQL** su dati Inside Airbnb di **Roma**.
Storage, vettori e analytics vivono su **Databricks**; la UI Streamlit gira in locale
e li interroga via API.

Doppia pipeline (requisito d'esame — analisi grounded, non solo QA documentale):

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
   ▼ Vector Search (Delta Sync,        ▼ SQL Warehouse
     embed via endpoint)                 (Text-to-SQL)
   review_chunks_index                   listings_enriched
                    ▲                     ▲
                    └──── ui/app_streamlit.py (locale) ────┘
                         intent → rag_core | analytics_core → LLM endpoint
```

| Livello | Tecnologia |
|---|---|
| ETL batch | notebook Spark su Databricks (serverless) |
| Storage | Unity Catalog (Delta tables, Volume per i raw) |
| Retrieval | Databricks Vector Search (Delta Sync, embedding lato Databricks) |
| Analytics | Databricks SQL Warehouse (Statement Execution API) |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (locale, MPS) |
| LLM + embedding | Databricks serving endpoint |
| UI | Streamlit locale (chiama Databricks via REST) |
| Config | `.env` + pydantic-settings |

---

## Struttura repo

```
databricks/   notebook ETL native (girano su Databricks)
  01_ingest_clean.py   raw Volume -> bronze/silver Delta (cap recensioni via widget)
  02_chunk.py          silver_reviews -> gold_review_chunks (CDF on, per Vector Search)
  03_analytics.py      vista listings_enriched (join listings⋈neighbourhoods)
  04_vector_index.py   endpoint Vector Search + indice Delta Sync
core/         librerie locali in-process
  config, llm_client, intent_classifier, reranker (locale),
  vectorstore (client Vector Search), analytics_core (SQL Warehouse), rag_core, observability
ui/app_streamlit.py    entrypoint UI
scripts/check_databricks.py   verifica workspace (endpoint + probe LLM/embedding)
evaluation/   retrieval (VS), generation (LLM-judge), latency
```

---

## Setup locale

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # compila HOST, TOKEN, SQL_WAREHOUSE_ID
```

## Collegamento Databricks (CLI)

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com --profile trial
databricks tokens create --comment airbnb-rag -p trial   # -> DATABRICKS_TOKEN in .env
python -m scripts.check_databricks                        # verifica endpoint + crediti
```

`check_databricks` elenca i serving endpoint e testa LLM + embedding. Se i nomi
differiscono, aggiornali in `.env`.

## Pipeline ETL (su Databricks)

Carica i notebook e i dati nel workspace, poi eseguili in ordine (UI Databricks o job):

```bash
# dati raw -> Volume UC (esempio Roma)
databricks fs mkdir dbfs:/Volumes/workspace/airbnb/raw/rome -p trial
databricks fs cp data/raw/rome/listings.csv        dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/neighbourhoods.csv  dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/reviews.csv.gz      dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
# notebook -> workspace
databricks workspace import-dir databricks /Workspace/Users/<you>/airbnb-rag --overwrite -p trial
```

Ordine: `01_ingest_clean` → `02_chunk` → `03_analytics` → `04_vector_index`.
Il widget `max_reviews` del notebook 01 limita le recensioni (costo embedding).

## Avvio UI

```bash
streamlit run ui/app_streamlit.py
```

Sidebar: selezione città, stato componenti (Databricks/Vector Search/Warehouse), metriche.

## Valutazione (§8)

```bash
python -m evaluation.retrieval_eval  --query-set evaluation/query_set.json --k 5
python -m evaluation.generation_eval --query-set evaluation/query_set.json
python -m evaluation.latency_bench   --rag "quiet clean flat" --sql "avg price by room type" --city rome
```

---

## Scope dati / costi

Progetto ristretto a **Roma**. Il widget `max_reviews` del notebook 01 (default 20k) limita
volume e costo embedding. Nota: l'endpoint embedding pay-per-token embedda a ~2 righe/sec via
Vector Search, quindi tenere il cap basso conviene; l'endpoint Vector Search ha inoltre un
costo *standing* finché attivo.

## Sicurezza

La SQL generata dal LLM è non fidata: `analytics_core.validate_and_sanitize` impone
whitelist **SELECT/WITH-only** (no DDL/DML, statement singolo). Token solo in `.env` (gitignored).
