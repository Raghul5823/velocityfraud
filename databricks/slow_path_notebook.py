# Databricks notebook source
# VelocityFraud — Slow Path on Databricks (Spark Structured Streaming + DistilBERT UDF)
#
# Closes proposal deliverables:
#   - Spark Structured Streaming slow path (Bronze -> Silver, micro-batch)
#   - DistilBERT text-anomaly as a Spark UDF (Item 4)
#   - Delta Lake medallion tables (Bronze / Silver)
#   - SQL-queryable Silver table for Power BI DirectQuery (Item 6)
#
# Environment: Databricks Free Edition, Serverless compute, Unity Catalog.
# Data: scored_events exported from local Postgres and uploaded as the Bronze table
#       `dbacademy.default.scored_events_bronze` (4,692 rows).
#
# NOTE ON FREE-EDITION CONSTRAINTS (why the code is shaped this way):
#   * Cloud Databricks cannot reach the local Docker Kafka (localhost:9092), so the
#     slow path reads the uploaded Bronze Delta table as a streaming source instead
#     of Kafka. This still exercises real Structured Streaming (readStream/writeStream).
#   * Spark workers could not download the HF model, so we pre-download DistilBERT on
#     the driver to a Volume and load it OFFLINE inside the UDF.
#   * The UDF scores in 32-row chunks and softmaxes only the masked position to stay
#     within the serverless worker memory limit.

# COMMAND ----------
# Cell 1 — verify the uploaded Bronze Delta table
BRONZE = "dbacademy.default.scored_events_bronze"
bronze = spark.read.table(BRONZE)
print("Bronze rows:", bronze.count())
display(bronze.select("event_id", "merchant_name", "fraud_score", "decision").limit(10))

# COMMAND ----------
# Cell 2 — install NLP libs (driver + serverless env), then restart the kernel
# MAGIC %pip install transformers torch --quiet
dbutils.library.restartPython()

# COMMAND ----------
# Cell A — download DistilBERT once on the DRIVER, save to a Volume (offline reuse)
from transformers import AutoTokenizer, AutoModelForMaskedLM
LOCAL = "/Volumes/dbacademy/default/tutorials/distilbert_mlm"
AutoTokenizer.from_pretrained("distilbert-base-uncased").save_pretrained(LOCAL)
AutoModelForMaskedLM.from_pretrained("distilbert-base-uncased").save_pretrained(LOCAL)
print("Model saved ->", LOCAL)

# COMMAND ----------
# Cell 3 — DistilBERT text-anomaly Pandas UDF (loads local/offline; memory-safe)
import os, pandas as pd
from pyspark.sql.functions import pandas_udf
from pyspark.sql.types import DoubleType

LOCAL = "/Volumes/dbacademy/default/tutorials/distilbert_mlm"
_M = {}
def _get_model():
    if "mdl" not in _M:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from transformers import AutoTokenizer, AutoModelForMaskedLM
        _M["tok"] = AutoTokenizer.from_pretrained(LOCAL)
        _M["mdl"] = AutoModelForMaskedLM.from_pretrained(LOCAL).eval()
        _M["torch"] = torch
    return _M["tok"], _M["mdl"], _M["torch"]

@pandas_udf(DoubleType())
def text_anomaly_score(names: pd.Series) -> pd.Series:
    """DistilBERT masked-LM anomaly score for merchant names. 32-row chunks +
    softmax only at the masked position => bounded worker memory. Higher score =
    more surprising/anomalous text (typosquats, missing/odd merchant domains)."""
    tok, mdl, torch = _get_model()
    vals = [(t or "").strip() or "[UNK]" for t in names]
    out, CH = [], 32
    for i in range(0, len(vals), CH):
        chunk = vals[i:i + CH]
        enc = tok(chunk, return_tensors="pt", padding=True, truncation=True, max_length=20)
        ids, attn = enc["input_ids"], enc["attention_mask"]
        B, L = ids.shape
        masked = ids.clone()
        pos = []
        for b in range(B):
            length = int(attn[b].sum().item())
            p = max(1, length // 2) if length > 2 else min(1, L - 1)
            pos.append(p)
            masked[b, p] = tok.mask_token_id
        with torch.no_grad():
            logits = mdl(masked, attention_mask=attn).logits
            mp = logits[torch.arange(B), torch.tensor(pos), :]
            lp = torch.log_softmax(mp, dim=-1)
            out.extend(float(-lp[b, ids[b, pos[b]]].item()) for b in range(B))
        del logits, mp, lp
    return pd.Series(out)

print("DistilBERT text-anomaly UDF registered (chunked, memory-safe).")

# COMMAND ----------
# Cell 4 — Structured Streaming: Bronze -> (DistilBERT UDF) -> Silver Delta
from pyspark.sql.functions import col, when

spark.sql("DROP TABLE IF EXISTS dbacademy.default.scored_events_silver")
dbutils.fs.rm("/Volumes/dbacademy/default/tutorials/ckpt_silver", recurse=True)

BRONZE = "dbacademy.default.scored_events_bronze"
SILVER = "dbacademy.default.scored_events_silver"
CKPT   = "/Volumes/dbacademy/default/tutorials/ckpt_silver"

stream = (spark.readStream.table(BRONZE)
    .withColumn("text_anomaly_score", text_anomaly_score(col("merchant_name")))
    .withColumn("text_suspicious", when(col("text_anomaly_score") >= 6.0, True).otherwise(False)))

q = (stream.writeStream
    .format("delta")
    .option("checkpointLocation", CKPT)
    .trigger(availableNow=True)          # Structured Streaming: process all, then stop
    .toTable(SILVER))
q.awaitTermination()
print("Silver written:", spark.read.table(SILVER).count(), "rows")

# COMMAND ----------
# Cell 5 — inspect the enriched Silver table
from pyspark.sql.functions import col
silver = spark.read.table("dbacademy.default.scored_events_silver")
print("Silver rows:", silver.count())
display(silver.select("merchant_name", "text_anomaly_score", "text_suspicious",
                      "fraud_score", "decision")
        .orderBy(col("text_anomaly_score").desc()).limit(20))

# COMMAND ----------
# Cell 6 — SQL aggregation (what Power BI DirectQuery reads)
# MAGIC %sql
# MAGIC SELECT decision,
# MAGIC        COUNT(*)                                        AS n,
# MAGIC        ROUND(AVG(text_anomaly_score), 3)               AS avg_text_anomaly,
# MAGIC        SUM(CASE WHEN text_suspicious THEN 1 ELSE 0 END) AS suspicious_count
# MAGIC FROM dbacademy.default.scored_events_silver
# MAGIC GROUP BY decision
# MAGIC ORDER BY n DESC
#
# Result (2026-08-13):
#   ALLOW  4668  avg=4.795  suspicious=1837
#   REVIEW   18  avg=1.441  suspicious=0
#   BLOCK     6  avg=0.828  suspicious=0
# => the DistilBERT text-anomaly signal is independent of the XGBoost fraud score;
#    the slow path surfaces 1,837 textually-suspicious merchants the fast path allowed.
