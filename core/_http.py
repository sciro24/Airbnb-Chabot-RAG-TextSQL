"""HTTP verso i serving endpoint Databricks: retry con backoff, timeout, timing.

Il contatore errori vive in `observability.METRICS`.
"""
from __future__ import annotations

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import Settings
from core.observability import METRICS


class EndpointError(RuntimeError):
    """Raised when a serving endpoint call ultimately fails."""


def _session(settings: Settings) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {settings.databricks_token}",
        "Content-Type": "application/json",
    })
    return s


def post_invocations(settings: Settings, endpoint_name: str, payload: dict, phase: str) -> dict:
    """POST a un serving endpoint /invocations con retry + timing. `phase` = bucket observability."""
    settings.require_databricks()
    url = settings.endpoint_url(endpoint_name)

    @retry(
        reraise=True,
        stop=stop_after_attempt(settings.http_max_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def _do() -> dict:
        with _session(settings) as sess:
            resp = sess.post(url, json=payload, timeout=settings.http_timeout_seconds)
        if resp.status_code >= 500 or resp.status_code == 429:  # transient -> retry
            raise requests.HTTPError(f"{resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:  # 4xx client error -> no retry
            raise EndpointError(f"{endpoint_name} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    with METRICS.timer(phase):
        try:
            return _do()
        except EndpointError:
            METRICS.record_error(phase)
            raise
        except requests.RequestException as exc:
            METRICS.record_error(phase)
            raise EndpointError(f"{endpoint_name} unreachable: {exc}") from exc
