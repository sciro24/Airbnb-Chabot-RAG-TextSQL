"""Ramo analytics: Text-to-SQL -> esecuzione su Databricks SQL Warehouse -> risposta NL.

Sicurezza: la SQL generata dal LLM non è fidata -> `validate_and_sanitize` impone
whitelist SELECT/WITH-only (no DDL/DML, statement singolo) prima dell'esecuzione.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

from core import llm_client
from core.config import Settings, get_settings
from core.observability import METRICS

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|"
    r"replace|truncate|grant|revoke|call|export|install|load|set|merge)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    """SQL generata non conforme alla whitelist SELECT-only."""


@dataclass
class AnalyticsResult:
    answer: str
    sql: str
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)


def _run_sql(settings: Settings, sql: str) -> tuple[list[str], list[list]]:
    """Esegue SQL sul warehouse via Statement Execution API."""
    if not settings.sql_warehouse_id:
        raise RuntimeError("SQL_WAREHOUSE_ID non impostato in .env")
    url = f"{settings.api_base}/api/2.0/sql/statements"
    payload = {
        "warehouse_id": settings.sql_warehouse_id,
        "statement": sql,
        "wait_timeout": "50s",
        "format": "JSON_ARRAY",
    }
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {settings.databricks_token}"},
        json=payload, timeout=settings.http_timeout_seconds + 30)
    if resp.status_code >= 400:
        raise RuntimeError(f"SQL API -> {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    state = data.get("status", {}).get("state")
    if state != "SUCCEEDED":
        msg = data.get("status", {}).get("error", {}).get("message", state)
        raise RuntimeError(f"SQL non riuscita ({state}): {msg}")
    cols = [c["name"] for c in data.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = data.get("result", {}).get("data_array", []) or []
    return cols, rows


# Cache dei quartieri (neighbourhood_display) per il prompt Text-to-SQL.
_NBH_CACHE: list[str] | None = None


def _neighbourhoods(settings: Settings) -> list[str]:
    global _NBH_CACHE
    if _NBH_CACHE is None:
        try:
            _, rows = _run_sql(
                settings, f"SELECT DISTINCT neighbourhood_display FROM {settings.analytics_table} "
                          "WHERE neighbourhood_display IS NOT NULL ORDER BY 1")
            _NBH_CACHE = [r[0] for r in rows]
        except Exception:
            _NBH_CACHE = []
    return _NBH_CACHE


def get_schema_description(settings: Settings) -> str:
    """Schema esposto al modello Text-to-SQL (colonne principali, solo Roma)."""
    nbhs = _neighbourhoods(settings)
    nbh_line = ("Quartieri (colonna neighbourhood_display): " + ", ".join(nbhs) + ".\n"
                "Se l'utente cita un quartiere con nome comune (es. 'eur', 'trastevere', 'centro'), "
                "mappalo al valore corrispondente filtrando con `neighbourhood_display ILIKE '%<nome>%'`.\n"
                ) if nbhs else ""
    return (
        f"Tabella: {settings.analytics_table} (contiene SOLO alloggi di Roma)\n"
        "Colonne principali: id, name, host_name, neighbourhood_display (quartiere/municipio), "
        "room_type, price (double, EUR), minimum_nights, number_of_reviews, reviews_per_month, "
        "availability_365.\n"
        + nbh_line
    )


def _text_to_sql_prompt(query: str, schema_context: str, table: str) -> str:
    return (
        "Sei un generatore di SQL per Databricks (Spark SQL). Genera UNA sola query SELECT.\n"
        "Regole: solo SELECT, nessun DDL/DML, nessun commento, nessun markdown.\n"
        f"Interroga esclusivamente la tabella `{table}`.\n"
        "IMPORTANTE: se la domanda cita un quartiere/zona/luogo, DEVI aggiungere la clausola "
        "WHERE con `neighbourhood_display ILIKE '%<nome>%'`.\n\n"
        f"{schema_context}\n"
        f"Esempio — Domanda: \"prezzo medio all'Eur\" -> "
        f"SELECT avg(price) FROM {table} WHERE neighbourhood_display ILIKE '%eur%'\n\n"
        f"Domanda: {query}\n\nRestituisci SOLO la query SQL:"
    )


# Il modello che formatta la risposta NON deve rivelare dettagli interni.
NL_SYSTEM = (
    "Formatti in linguaggio naturale il risultato di una query sui dati Airbnb di Roma. "
    "NON menzionare tabelle, colonne, SQL, schema o dettagli tecnici interni. "
    "Tutti i dati riguardano SOLO Roma: non aggiungere avvisi sul fatto che non siano di Roma. "
    "Rispondi conciso, grounded sui numeri, nella lingua della domanda."
)


def _result_to_nl_prompt(query: str, preview_md: str) -> str:
    return f"Domanda: {query}\n\nRisultato:\n{preview_md}\n\nRisposta:"


def _strip_fences(sql: str) -> str:
    sql = sql.strip()
    sql = re.sub(r"^```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = re.sub(r"```$", "", sql).strip()
    return sql


def validate_and_sanitize(sql: str) -> str:
    """Impone statement SELECT/WITH singolo. Solleva UnsafeSQLError altrimenti."""
    sql = _strip_fences(sql).rstrip(";").strip()
    if not sql:
        raise UnsafeSQLError("SQL vuota")
    if ";" in sql:
        raise UnsafeSQLError("Statement multipli non consentiti")
    low = sql.lstrip("(").lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise UnsafeSQLError("Sono consentite solo query SELECT/WITH")
    if FORBIDDEN.search(sql):
        raise UnsafeSQLError("Keyword vietata nella SQL generata")
    return sql


def _preview_markdown(columns: list[str], rows: list[list], limit: int = 20) -> str:
    head = " | ".join(columns)
    sep = " | ".join("---" for _ in columns)
    body = "\n".join(" | ".join(str(v) for v in r) for r in rows[:limit])
    return f"{head}\n{sep}\n{body}"


def prepare(query: str, settings: Settings | None = None) -> tuple[AnalyticsResult, str]:
    """NL->SQL, sanitize ed esegue. Ritorna (risultato parziale senza answer, prompt NL)."""
    settings = settings or get_settings()
    table = settings.analytics_table
    raw_sql = llm_client.generate(
        _text_to_sql_prompt(query, get_schema_description(settings), table),
        system="Rispondi solo con SQL Spark valido, nient'altro.",
        temperature=0.0, settings=settings)
    sql = validate_and_sanitize(raw_sql)

    with METRICS.timer("sql_exec"):
        columns, rows = _run_sql(settings, sql)

    preview_md = _preview_markdown(columns, rows) if rows else "(nessuna riga)"
    res = AnalyticsResult(answer="", sql=sql, row_count=len(rows), columns=columns,
                          preview=[dict(zip(columns, r)) for r in rows[:20]])
    return res, _result_to_nl_prompt(query, preview_md)


def answer_analytics(query: str, settings: Settings | None = None) -> AnalyticsResult:
    settings = settings or get_settings()
    res, nl_prompt = prepare(query, settings)
    res.answer = llm_client.generate(nl_prompt, system=NL_SYSTEM, temperature=0.2, settings=settings)
    return res
