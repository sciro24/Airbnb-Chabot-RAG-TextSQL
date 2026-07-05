"""Wrapper endpoint LLM Databricks (chat OpenAI-compatible `/invocations`)."""
from __future__ import annotations

import json
from typing import Iterator

import requests

from core._http import post_invocations
from core.config import Settings, get_settings


def _content_to_text(content) -> str:
    """Estrae il testo di risposta da `content`.

    I modelli normali ritornano una stringa. I reasoning model (es. gpt-oss)
    ritornano una LISTA di parti: `reasoning` (da saltare) + una parte finale
    `text`/`output_text` (la risposta). Se c'è solo reasoning (risposta troncata)
    si ripiega sul riassunto del reasoning.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        answer, reasoning = [], []
        for part in content:
            if not isinstance(part, dict):
                answer.append(str(part))
                continue
            ptype = part.get("type", "")
            if ptype in ("text", "output_text") and part.get("text"):
                answer.append(part["text"])
            elif ptype == "reasoning":
                for s in part.get("summary", []) or []:
                    if isinstance(s, dict) and s.get("text"):
                        reasoning.append(s["text"])
        return "".join(answer) if answer else " ".join(reasoning)
    return str(content)


def _parse_chat(resp: dict) -> str:
    """Estrae il testo dell'assistant dalle forme di risposta comuni."""
    if "choices" in resp:  # forma OpenAI (normale o reasoning)
        choice = resp["choices"][0]
        if "message" in choice:
            return _content_to_text(choice["message"].get("content", ""))
        if "text" in choice:
            return choice["text"]
    if "predictions" in resp:  # forma MLflow Databricks
        pred = resp["predictions"]
        if isinstance(pred, list) and pred:
            first = pred[0]
            if isinstance(first, dict):
                return first.get("candidates", [{}])[0].get("text") or str(first)
            return str(first)
    raise ValueError(f"Risposta chat non riconosciuta: {list(resp)[:5]}")


def generate(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    settings: Settings | None = None,
) -> str:
    """Generazione single-turn. `system` = prompt di sistema opzionale."""
    settings = settings or get_settings()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    resp = post_invocations(settings, settings.llm_endpoint_name, payload, phase="generate")
    return _parse_chat(resp).strip()


def _delta_text(delta: dict) -> str:
    """Estrae il testo di risposta da un delta streaming, saltando il reasoning."""
    c = delta.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c
                       if isinstance(p, dict) and p.get("type") in ("text", "output_text"))
    return ""


def generate_stream(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    settings: Settings | None = None,
) -> Iterator[str]:
    """Come `generate` ma in streaming: produce i chunk di testo della risposta.

    Salta i token di reasoning (gpt-oss): finché il modello ragiona non emette nulla.
    """
    settings = settings or get_settings()
    settings.require_databricks()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"messages": messages, "temperature": temperature,
               "max_tokens": max_tokens, "stream": True}
    resp = requests.post(
        settings.endpoint_url(settings.llm_endpoint_name),
        headers={"Authorization": f"Bearer {settings.databricks_token}"},
        json=payload, stream=True, timeout=settings.http_timeout_seconds + 60)
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line or not line.startswith(b"data: "):
            continue
        body = line[6:]
        if body.strip() == b"[DONE]":
            break
        try:
            delta = json.loads(body)["choices"][0].get("delta", {})
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
        text = _delta_text(delta)
        if text:
            yield text
