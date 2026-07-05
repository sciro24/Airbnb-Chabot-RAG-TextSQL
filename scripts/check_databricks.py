"""Verifica connettività di un workspace Databricks.

Da lanciare dopo aver puntato `.env` a un nuovo workspace. Fa:
  1. lista dei serving endpoint disponibili (i nomi variano per account);
  2. probe dell'endpoint LLM con una generazione minima;
  3. probe dell'endpoint embedding con un embed minimo.

Nessun dato scritto, ogni probe è una singola richiesta. I segreti non vengono stampati.

    python -m scripts.check_databricks
"""
from __future__ import annotations

import sys

import requests

from core.config import get_settings


def _mask(tok: str) -> str:
    return f"{tok[:8]}…({len(tok)} chars)" if tok else "<empty>"


def list_serving_endpoints(settings) -> list[dict]:
    url = f"{settings.databricks_host.rstrip('/')}/api/2.0/serving-endpoints"
    headers = {"Authorization": f"Bearer {settings.databricks_token}"}
    resp = requests.get(url, headers=headers, timeout=settings.http_timeout_seconds)
    resp.raise_for_status()
    return resp.json().get("endpoints", [])


def main() -> int:
    settings = get_settings()
    print("=" * 60)
    print("Verifica workspace Databricks")
    print("=" * 60)
    print(f"HOST:              {settings.databricks_host or '<empty>'}")
    print(f"TOKEN:             {_mask(settings.databricks_token)}")
    print(f"LLM endpoint:      {settings.llm_endpoint_name}")
    print(f"Embedding endpoint:{settings.embedding_endpoint_name}")
    print(f"Vector Search:     {settings.vs_endpoint} / {settings.vs_index}")
    print(f"SQL Warehouse:     {settings.sql_warehouse_id or '<empty>'}")
    print()

    try:
        settings.require_databricks()
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 1

    ok = True

    # 1) elenco endpoint
    print("--- Serving endpoint nel workspace ---")
    try:
        eps = list_serving_endpoints(settings)
        if not eps:
            print("  (nessuno trovato)")
        for ep in eps:
            state = ep.get("state", {}).get("ready", "?")
            print(f"  • {ep.get('name')}  [ready={state}]")
        names = {ep.get("name") for ep in eps}
        if settings.llm_endpoint_name not in names:
            print(f"  ⚠️  LLM '{settings.llm_endpoint_name}' non in lista — aggiorna LLM_ENDPOINT_NAME in .env")
    except Exception as exc:
        print(f"  ⚠️  impossibile elencare gli endpoint ({str(exc)[:120]})")
        print("      (il token potrebbe non avere lo scope API; i probe sotto dicono cosa funziona)")
    print()

    # 2) probe LLM
    print("--- Probe LLM ---")
    try:
        from core import llm_client

        out = llm_client.generate("Rispondi con una parola: ok", temperature=0.0, max_tokens=512)
        print(f"  ✅ LLM OK -> {out[:60]!r}")
    except Exception as exc:
        ok = False
        print(f"  ❌ LLM FAIL -> {type(exc).__name__}: {str(exc)[:200]}")

    # 3) probe embedding (endpoint usato da Vector Search)
    print("--- Probe embedding ---")
    try:
        url = settings.endpoint_url(settings.embedding_endpoint_name)
        r = requests.post(url, headers={"Authorization": f"Bearer {settings.databricks_token}"},
                          json={"input": ["ping"]}, timeout=settings.http_timeout_seconds)
        r.raise_for_status()
        dim = len(r.json()["data"][0]["embedding"])
        print(f"  ✅ Embedding OK -> dim {dim}")
    except Exception as exc:
        ok = False
        print(f"  ❌ Embedding FAIL -> {type(exc).__name__}: {str(exc)[:200]}")

    print()
    print("ESITO:", "✅ tutti i probe passati" if ok else "❌ alcuni probe falliti — vedi sopra")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
