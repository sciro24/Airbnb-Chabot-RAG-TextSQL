"""Settings da `.env` (pydantic-settings). Non committare mai `.env`."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# Progetto ristretto a Roma per semplicità.
CITY = "rome"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Databricks serving endpoints ----
    databricks_host: str = Field(default="", alias="DATABRICKS_HOST")
    databricks_token: str = Field(default="", alias="DATABRICKS_TOKEN")
    llm_endpoint_name: str = Field(default="databricks-gpt-oss-20b", alias="LLM_ENDPOINT_NAME")
    # Endpoint embedding: usato lato Databricks da Vector Search (non embeddiamo in locale).
    embedding_endpoint_name: str = Field(
        default="databricks-qwen3-embedding-0-6b", alias="EMBEDDING_ENDPOINT_NAME"
    )

    # ---- Storage/retrieval native (Unity Catalog + Vector Search + SQL Warehouse) ----
    uc_catalog: str = Field(default="workspace", alias="UC_CATALOG")
    uc_schema: str = Field(default="airbnb", alias="UC_SCHEMA")
    vs_endpoint: str = Field(default="airbnb-vs", alias="VS_ENDPOINT")
    vs_index: str = Field(default="workspace.airbnb.review_chunks_index", alias="VS_INDEX")
    sql_warehouse_id: str = Field(default="", alias="SQL_WAREHOUSE_ID")

    # ---- Reranker locale ----
    reranker_model: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", alias="RERANKER_MODEL"
    )
    reranker_device: str = Field(default="mps", alias="RERANKER_DEVICE")

    # ---- Runtime ----
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")
    http_timeout_seconds: int = Field(default=30, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")
    retrieval_top_k: int = Field(default=20, alias="RETRIEVAL_TOP_K")
    rerank_top_k: int = Field(default=3, alias="RERANK_TOP_K")

    @property
    def analytics_table(self) -> str:
        """Vista denormalizzata interrogata dal ramo Text-to-SQL."""
        return f"{self.uc_catalog}.{self.uc_schema}.listings_enriched"

    @property
    def api_base(self) -> str:
        return self.databricks_host.rstrip("/")

    def endpoint_url(self, endpoint_name: str) -> str:
        return f"{self.api_base}/serving-endpoints/{endpoint_name}/invocations"

    def require_databricks(self) -> None:
        """Errore chiaro se mancano le credenziali."""
        if not self.databricks_host or not self.databricks_token:
            raise RuntimeError(
                "DATABRICKS_HOST/DATABRICKS_TOKEN mancanti: copia .env.example in .env e compila."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton: `.env` letto una volta per processo."""
    return Settings()
