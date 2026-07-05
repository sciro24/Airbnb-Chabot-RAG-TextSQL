# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest & Clean (solo Roma)
# MAGIC Legge i CSV di Roma dal Volume UC, tipizza/pulisce, scrive tabelle Delta bronze+silver.
# MAGIC Cap recensioni via widget (default 20k) per contenere il costo embedding.

# COMMAND ----------

# MAGIC %pip install langdetect
# MAGIC %restart_python

# COMMAND ----------

# Campiona N recensioni per annuncio sui M annunci più recensiti: distribuisce le
# recensioni su molti alloggi (per la mappa) invece di concentrarle sui primi id.
dbutils.widgets.text("reviews_per_listing", "6", "Recensioni per annuncio")
dbutils.widgets.text("max_listings", "2000", "Numero di annunci da coprire")

CATALOG, SCHEMA, CITY = "workspace", "airbnb", "rome"
VOL = f"/Volumes/{CATALOG}/{SCHEMA}/raw/{CITY}"
REV_PER_LISTING = int(dbutils.widgets.get("reviews_per_listing") or 6)
MAX_LISTINGS = int(dbutils.widgets.get("max_listings") or 2000)
spark.sql(f"USE CATALOG {CATALOG}"); spark.sql(f"USE SCHEMA {SCHEMA}")
print("città:", CITY, "| rec/annuncio:", REV_PER_LISTING, "| annunci:", MAX_LISTINGS)

# COMMAND ----------

from pyspark.sql import functions as F, types as T

# Colonne canoniche selezionate PER NOME (robusto a colonne extra/ordini diversi)
LISTINGS_COLS = {
    "id": "long", "name": "string", "host_id": "long", "host_name": "string",
    "neighbourhood_group": "string", "neighbourhood": "string", "latitude": "double",
    "longitude": "double", "room_type": "string", "price": "string",
    "minimum_nights": "int", "number_of_reviews": "int", "last_review": "string",
    "reviews_per_month": "double", "calculated_host_listings_count": "int",
    "availability_365": "int", "number_of_reviews_ltm": "int", "license": "string",
}
REVIEWS_COLS = {"listing_id": "long", "id": "long", "date": "string",
                "reviewer_id": "long", "reviewer_name": "string", "comments": "string"}
NEIGH_COLS = {"neighbourhood_group": "string", "neighbourhood": "string"}


def read_csv(path, cols):
    """Legge CSV per header (all-string) e casta le colonne canoniche per nome; aggiunge city."""
    raw = (spark.read.option("header", True).option("inferSchema", False)
           .option("multiLine", True).option("escape", '"').option("quote", '"').csv(path))
    present = set(raw.columns)
    sel = [F.col(c).cast(t).alias(c) if c in present else F.lit(None).cast(t).alias(c)
           for c, t in cols.items()]
    return (raw.select(*sel).withColumn("city", F.lit(CITY))
            .withColumn("ingestion_ts", F.current_timestamp()))

# COMMAND ----------

# --- BRONZE listings/neighbourhoods ---
read_csv(f"{VOL}/listings.csv", LISTINGS_COLS).write.mode("overwrite").saveAsTable("bronze_listings")
read_csv(f"{VOL}/neighbourhoods.csv", NEIGH_COLS).write.mode("overwrite").saveAsTable("bronze_neighbourhoods")

# --- BRONZE reviews: N recensioni per annuncio sui M annunci più recensiti ---
from pyspark.sql import Window

target = (spark.table("bronze_listings").filter(F.col("number_of_reviews") > 0)
          .orderBy(F.desc("number_of_reviews")).limit(MAX_LISTINGS)
          .select(F.col("id").alias("listing_id")))
w = Window.partitionBy("listing_id").orderBy(F.desc("date"))
rev = (read_csv(f"{VOL}/reviews.csv.gz", REVIEWS_COLS)
       .withColumn("rn", F.row_number().over(w)).filter(F.col("rn") <= REV_PER_LISTING).drop("rn")
       .join(target, "listing_id", "inner"))
rev.write.mode("overwrite").saveAsTable("bronze_reviews")
print("bronze reviews:", spark.table("bronze_reviews").count(),
      "| annunci:", spark.table("bronze_reviews").select("listing_id").distinct().count())

# COMMAND ----------

# --- SILVER listings: price->double, normalizza neighbourhood, drop null chiave ---
price = F.regexp_replace(F.col("price").cast("string"), r"[$,]", "")
lc = (spark.table("bronze_listings")
      .withColumn("price", F.when(price == "", None).otherwise(price).cast("double"))
      .withColumn("neighbourhood_display", F.col("neighbourhood"))
      .withColumn("neighbourhood", F.lower(F.trim("neighbourhood")))
      .withColumn("neighbourhood_group", F.lower(F.trim("neighbourhood_group")))
      .dropna(subset=["price", "room_type"]))
lc.write.mode("overwrite").saveAsTable("silver_listings")

# --- SILVER neighbourhoods: normalizza + dedup ---
nc = (spark.table("bronze_neighbourhoods")
      .withColumn("neighbourhood_display", F.col("neighbourhood"))
      .withColumn("neighbourhood", F.lower(F.trim("neighbourhood")))
      .withColumn("neighbourhood_group", F.lower(F.trim("neighbourhood_group")))
      .dropDuplicates(["neighbourhood"]))
nc.write.mode("overwrite").saveAsTable("silver_neighbourhoods")
print("silver_listings:", lc.count(), "| silver_neighbourhoods:", nc.count())

# COMMAND ----------

# --- SILVER reviews: pulizia testo, filtro lingua EN+IT, dedup ---
@F.udf(T.StringType())
def detect_lang(txt):
    try:
        from langdetect import detect
        return detect(txt) if txt and len(txt) > 12 else "unknown"
    except Exception:
        return "unknown"

r = (spark.table("bronze_reviews")
     .withColumn("comments", F.trim(F.regexp_replace("comments", r"<[^>]+>", " ")))
     .withColumn("comments", F.trim(F.regexp_replace("comments", r"\s+", " ")))
     .filter(F.col("comments").isNotNull() & (F.col("comments") != ""))
     .withColumn("lang", detect_lang("comments"))
     .filter(F.col("lang").isin("en", "it"))
     .dropDuplicates(["listing_id", "reviewer_id", "date"]))
r.write.mode("overwrite").saveAsTable("silver_reviews")
print("silver_reviews:", r.count())
