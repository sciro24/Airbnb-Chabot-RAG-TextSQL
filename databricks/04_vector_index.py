# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Vector Search index
# MAGIC Crea endpoint Vector Search + indice **Delta Sync** su `gold_review_chunks`.
# MAGIC Gli embedding li calcola Databricks usando l'endpoint `databricks-qwen3-embedding-0-6b`
# MAGIC (nessun loop di embedding manuale). Sync `TRIGGERED` = on-demand, più economico.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------

ENDPOINT = "airbnb-vs"
INDEX = "workspace.airbnb.review_chunks_index"
SOURCE = "workspace.airbnb.gold_review_chunks"
EMBED_ENDPOINT = "databricks-qwen3-embedding-0-6b"

from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient()

# COMMAND ----------

# Endpoint (compute standing: consuma crediti finché attivo)
existing = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
if ENDPOINT not in existing:
    vsc.create_endpoint_and_wait(name=ENDPOINT, endpoint_type="STANDARD")
print("endpoint pronto:", ENDPOINT)

# COMMAND ----------

# Indice Delta Sync: Databricks embedda `chunk_text` e mantiene i metadati per i filtri
try:
    idx = vsc.create_delta_sync_index_and_wait(
        endpoint_name=ENDPOINT,
        index_name=INDEX,
        source_table_name=SOURCE,
        pipeline_type="TRIGGERED",
        primary_key="chunk_id",
        embedding_source_column="chunk_text",
        embedding_model_endpoint_name=EMBED_ENDPOINT,
        columns_to_sync=["chunk_id", "listing_id", "city", "neighbourhood", "room_type", "review_date", "chunk_text"],
    )
    print("indice creato")
except Exception as e:
    # se esiste già, lancia solo il sync
    print("indice esistente, avvio sync:", str(e)[:80])
    idx = vsc.get_index(ENDPOINT, INDEX)
    idx.sync()

# COMMAND ----------

# Smoke test retrieval
import time; time.sleep(10)
res = vsc.get_index(ENDPOINT, INDEX).similarity_search(
    query_text="appartamento pulito e tranquillo vicino al centro",
    columns=["city", "neighbourhood", "chunk_text"], num_results=3)
print(res)
