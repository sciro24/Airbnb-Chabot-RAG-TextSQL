# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Chunking
# MAGIC `silver_reviews` (+ metadati listing) → `gold_review_chunks` (1 recensione = 1 chunk).
# MAGIC Tabella con Change Data Feed attivo: sorgente per l'indice Vector Search.

# COMMAND ----------

from pyspark.sql import functions as F, types as T
spark.sql("USE CATALOG workspace"); spark.sql("USE SCHEMA airbnb")

reviews = spark.table("silver_reviews")
assert "comments" in reviews.columns, "silver_reviews senza `comments`: serve l'export dettagliato"

# COMMAND ----------

# Arricchisce ogni recensione coi metadati del listing (per filtri metadata-aware)
listings = spark.table("silver_listings").select(
    F.col("id").alias("listing_id"), "city", "neighbourhood", "room_type")
r = reviews.join(listings, ["listing_id", "city"], "left")

# token_count approssimato (whitespace * 1.3) — solo per diagnostica
chunks = (r.select(
    F.expr("uuid()").alias("chunk_id"),
    "listing_id", "city", "neighbourhood", "room_type",
    F.col("date").alias("review_date"),
    F.col("comments").alias("chunk_text"),
    (F.size(F.split("comments", r"\s+")) * 1.3).cast("int").alias("token_count"))
    .filter(F.length("chunk_text") > 0))

# COMMAND ----------

# Scrive gold con CDF attivo (richiesto da Vector Search Delta Sync)
(chunks.write.mode("overwrite")
 .option("delta.enableChangeDataFeed", "true")
 .saveAsTable("gold_review_chunks"))
spark.sql("ALTER TABLE gold_review_chunks SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print("gold_review_chunks:", spark.table("gold_review_chunks").count())
display(spark.table("gold_review_chunks").limit(3))
