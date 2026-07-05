# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Analytics table
# MAGIC Vista denormalizzata `listings_enriched` (join listings⋈neighbourhoods) per il ramo Text-to-SQL.
# MAGIC Interrogata dalla UI via SQL Warehouse.

# COMMAND ----------

spark.sql("USE CATALOG workspace"); spark.sql("USE SCHEMA airbnb")

# Vista denormalizzata: evita di far scrivere il JOIN al modello Text-to-SQL
spark.sql("""
CREATE OR REPLACE VIEW listings_enriched AS
SELECT l.*, n.neighbourhood_group AS official_neighbourhood_group,
       n.neighbourhood_display   AS official_neighbourhood_display
FROM silver_listings l
LEFT JOIN silver_neighbourhoods n
  ON l.city = n.city AND l.neighbourhood = n.neighbourhood
""")

# COMMAND ----------

# Smoke test
display(spark.sql("SELECT city, count(*) n, round(avg(price),2) avg_price FROM listings_enriched GROUP BY city ORDER BY city"))
display(spark.sql("DESCRIBE listings_enriched"))
