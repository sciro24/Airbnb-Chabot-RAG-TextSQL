# Airbnb RAG + Analytics — Rome

A dual-pipeline conversational system over Inside Airbnb data for **Rome**. It combines
**Retrieval-Augmented Generation (RAG)** on guest reviews with **Text-to-SQL analytics** on
listings, exposed through a React web app backed by a FastAPI service. Storage, vector search,
and analytics run on **Databricks**; only a local cross-encoder reranker runs on the machine
hosting the API.

![Main page](docs/screenshots/home.png)

## What it does

A single chat interface answers three kinds of questions, routed automatically by an
LLM intent classifier:

- **Analytics** (`Text-to-SQL`): "What is the average price per room type?", "How many listings
  are in the Eur district?". The question is translated to Spark SQL, executed on a Databricks
  SQL Warehouse over the `listings_enriched` view, and the result is summarised in natural language.
- **RAG** (`reviews`): "Do guests complain about noise?", "What do reviews say about cleanliness?".
  The query hits a Databricks Vector Search index of review chunks, results are re-ranked locally
  with a cross-encoder, and an LLM produces a grounded answer that cites concrete guest feedback.
- **Conversational**: greetings and meta questions.

The map on the left shows every listing that has reviews in the vector index, grouped by the
15 official municipi. Users can click a listing to scope the chat to that specific property,
select a district from the dropdown to scope by neighbourhood, or ask a listing by name
("What do guests say about _Santini Home_?"). When a question is too broad for the whole city,
the assistant asks the user to pick a district first.

## Pipeline

![Pipeline](docs/screenshots/pipeline.png)

| Layer            | Technology                                                                                 |
| ---------------- | ------------------------------------------------------------------------------------------ |
| Batch ETL        | PySpark notebooks on Databricks (serverless)                                               |
| Storage          | Unity Catalog Delta tables; UC Volume for raw files                                        |
| Retrieval        | Databricks Vector Search (Delta Sync, server-side embeddings)                              |
| Analytics        | Databricks SQL Warehouse (Statement Execution API)                                         |
| Reranker         | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (local, MPS/CPU)                              |
| LLM + embeddings | Databricks serving endpoints (`databricks-gpt-oss-20b`, `databricks-qwen3-embedding-0-6b`) |
| Backend          | FastAPI (REST + SSE streaming); serves the frontend build                                  |
| Frontend         | React + Vite + Leaflet (map) + Recharts (metrics)                                          |
| Config           | `.env` via pydantic-settings                                                               |

## How it works

**Ingestion & preparation** (`databricks/` notebooks, run on Databricks):

1. `01_ingest_clean` — reads the raw CSVs from a UC Volume, casts columns by name (robust to
   schema drift), cleans prices (drops out-of-range outliers), and samples reviews with a
   **stratified strategy per district** (top _K_ listings per municipio, _N_ reviews each) so
   the map is balanced across neighbourhoods instead of dominated by the city centre. Writes
   `bronze_*` and `silver_*` Delta tables.
2. `02_chunk` — turns each review into one chunk with listing metadata; writes
   `gold_review_chunks` with Change Data Feed enabled (required by Vector Search Delta Sync).
3. `03_analytics` — builds the denormalised `listings_enriched` view used by Text-to-SQL.
4. `04_vector_index` — creates the Vector Search endpoint and a Delta Sync index; Databricks
   computes the embeddings server-side from `chunk_text`.

**Serving** (`api/` + `core/`, run locally or anywhere with network access to Databricks):

- `intent_classifier` routes the query. `analytics_core` generates SELECT-only SQL (validated
  against an allowlist) and runs it on the SQL Warehouse. `rag_core` queries Vector Search,
  re-ranks with the local cross-encoder, and builds a grounded prompt. `llm_client` streams the
  answer token by token (Server-Sent Events), skipping the reasoning tokens of the model.
- Responses are cached per `(query, scope)`; observability counters (intents, cache hit/miss,
  per-phase latency) are persisted to disk and shown on the metrics page.

![Observability page](docs/screenshots/metrics.png)

## Repository layout

```
databricks/   Databricks notebooks (.ipynb): 01 ingest+clean, 02 chunk, 03 analytics, 04 vector index
core/         in-process libraries: config, llm_client (streaming), intent_classifier,
              reranker, vectorstore (Vector Search client), analytics_core (SQL), rag_core, observability
api/          FastAPI backend: main.py (routes + SSE + SPA hosting), services.py, assets/ (geojson)
web/          React + Vite frontend (Home map+chat, Observability dashboard)
scripts/      check_databricks.py — workspace connectivity check
evaluation/   retrieval (Recall/MRR/nDCG), generation (LLM-as-judge), latency benchmarks
docs/         screenshots
```

## Setup

Requirements: Python 3.11+, Node 18+, Java 11+ (only for running the notebooks locally; on
Databricks it is provided), a Databricks workspace with model-serving credits.

```bash
# backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # fill in DATABRICKS_HOST, DATABRICKS_TOKEN, SQL_WAREHOUSE_ID

# frontend
cd web && npm install && npm run build && cd ..
```

### Connect to Databricks

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com --profile trial
databricks tokens create --comment airbnb-rag -p trial     # copy into DATABRICKS_TOKEN
python -m scripts.check_databricks                          # verify endpoints + credits
```

### Build the data (Databricks)

Upload the raw files to a UC Volume and the notebooks to the workspace, then run them in order:

```bash
databricks fs mkdir dbfs:/Volumes/workspace/airbnb/raw/rome -p trial
databricks fs cp data/raw/rome/listings.csv        dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/neighbourhoods.csv  dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks fs cp data/raw/rome/reviews.csv.gz      dbfs:/Volumes/workspace/airbnb/raw/rome/ -p trial
databricks workspace import-dir databricks /Workspace/Users/<you>/airbnb-rag --overwrite -p trial
```

Run `01_ingest_clean` → `02_chunk` → `03_analytics` → `04_vector_index`. The widgets on `01`
(`reviews_per_listing`, `listings_per_neighbourhood`) control coverage and embedding cost.

### Run the app

```bash
uvicorn api.main:app --port 8000      # open http://localhost:8000
```

For frontend development with hot reload, run the backend and `cd web && npm run dev` (Vite
proxies `/api` to port 8000).

## Evaluation

```bash
python -m evaluation.retrieval_eval  --query-set evaluation/query_set.json --k 5
python -m evaluation.generation_eval --query-set evaluation/query_set.json
python -m evaluation.latency_bench   --rag "clean quiet flat" --sql "average price by room type"
```

## Notes and limitations

- Data is restricted to Rome and to the sampled subset of reviews that is embedded in the
  vector index; the map shows roughly two thousand balanced listings, not the full inventory.
- The embedding endpoint used for Vector Search is rate-limited on pay-per-token workspaces,
  so a full index sync takes on the order of an hour; the Vector Search endpoint has a standing
  cost while it exists.
- Generated SQL is untrusted by construction: `analytics_core.validate_and_sanitize` enforces a
  single SELECT/WITH statement (no DDL/DML) before execution, and the SQL connection is read-only.
- Secrets live only in `.env`, which is gitignored.
