# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest & Clean (solo Roma)
# MAGIC Legge i CSV di Roma dal Volume UC, tipizza/pulisce, scrive tabelle Delta bronze+silver.
# MAGIC Cap recensioni via widget (default 20k) per contenere il costo embedding.

# COMMAND ----------

# MAGIC %pip install langdetect
# MAGIC %restart_python

# COMMAND ----------

# Campionamento STRATIFICATO per quartiere: per ogni municipio prende i K annunci più
# recensiti, e per ognuno N recensioni. Così la mappa è bilanciata tra i quartieri invece
# di concentrarsi sul Centro Storico (che ha molti più annunci).
dbutils.widgets.text("reviews_per_listing", "6", "Recensioni per annuncio")
dbutils.widgets.text("listings_per_neighbourhood", "150", "Annunci per quartiere")

CATALOG, SCHEMA, CITY = "workspace", "airbnb", "rome"
VOL = f"/Volumes/{CATALOG}/{SCHEMA}/raw/{CITY}"
REV_PER_LISTING = int(dbutils.widgets.get("reviews_per_listing") or 6)
LISTINGS_PER_NBH = int(dbutils.widgets.get("listings_per_neighbourhood") or 150)
# Prezzi validi (fuori range = junk: es. host che bloccano il calendario con 9000€).
PRICE_MIN, PRICE_MAX = 10.0, 5000.0
spark.sql(f"USE CATALOG {CATALOG}"); spark.sql(f"USE SCHEMA {SCHEMA}")
print("città:", CITY, "| rec/annuncio:", REV_PER_LISTING, "| annunci/quartiere:", LISTINGS_PER_NBH)

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

# --- BRONZE reviews: stratificato per quartiere (K annunci/quartiere, N recensioni/annuncio) ---
from pyspark.sql import Window

# Top K annunci per ciascun quartiere (per numero di recensioni)
w_nbh = Window.partitionBy("neighbourhood").orderBy(F.desc("number_of_reviews"))
target = (spark.table("bronze_listings").filter(F.col("number_of_reviews") > 0)
          .withColumn("rk", F.row_number().over(w_nbh))
          .filter(F.col("rk") <= LISTINGS_PER_NBH)
          .select(F.col("id").alias("listing_id")))
# N recensioni più recenti per ciascun annuncio target
w_rev = Window.partitionBy("listing_id").orderBy(F.desc("date"))
rev = (read_csv(f"{VOL}/reviews.csv.gz", REVIEWS_COLS)
       .join(target, "listing_id", "inner")
       .withColumn("rn", F.row_number().over(w_rev)).filter(F.col("rn") <= REV_PER_LISTING).drop("rn"))
rev.write.mode("overwrite").saveAsTable("bronze_reviews")
print("bronze reviews:", spark.table("bronze_reviews").count(),
      "| annunci:", spark.table("bronze_reviews").select("listing_id").distinct().count())

# COMMAND ----------

# --- SILVER listings: price->double (junk->null), normalizza neighbourhood, drop null chiave ---
price = F.regexp_replace(F.col("price").cast("string"), r"[$,]", "").cast("double")
# Prezzi fuori [PRICE_MIN, PRICE_MAX] = anomali -> null (esclusi dalle analytics)
price = F.when((price >= PRICE_MIN) & (price <= PRICE_MAX), price).otherwise(None)
lc = (spark.table("bronze_listings")
      .withColumn("price", price)
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
