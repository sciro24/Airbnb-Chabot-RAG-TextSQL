"""Observability: timing per fase, contatori intent, cache hit/miss.

Persistente su file (`.metrics.json` in repo root): sopravvive ai riavvii del server,
si azzera solo con `reset()`.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_MET_FILE = Path(__file__).resolve().parent.parent / ".metrics.json"


@dataclass
class Metrics:
    """Contatori + timing per fase, thread-safe, persistiti su file."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    intent_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cache_hits: int = 0
    cache_misses: int = 0
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # fase -> lista di durate in ms
    phase_timings: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def _save(self) -> None:
        """Salva lo stato su file (chiamare con lock acquisito)."""
        try:
            _MET_FILE.write_text(json.dumps({
                "intent_counts": dict(self.intent_counts),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "errors": dict(self.errors),
                "phase_timings": {k: v[-200:] for k, v in self.phase_timings.items()},
            }))
        except Exception:
            pass

    def load(self) -> None:
        """Carica lo stato dal file, se presente."""
        try:
            d = json.loads(_MET_FILE.read_text())
        except Exception:
            return
        with self._lock:
            self.intent_counts = defaultdict(int, d.get("intent_counts", {}))
            self.cache_hits = d.get("cache_hits", 0)
            self.cache_misses = d.get("cache_misses", 0)
            self.errors = defaultdict(int, d.get("errors", {}))
            self.phase_timings = defaultdict(list, d.get("phase_timings", {}))

    def record_intent(self, intent: str) -> None:
        with self._lock:
            self.intent_counts[intent] += 1
            self._save()

    def record_cache(self, hit: bool) -> None:
        with self._lock:
            if hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            self._save()

    def record_error(self, where: str) -> None:
        with self._lock:
            self.errors[where] += 1
            self._save()

    def record_phase(self, phase: str, ms: float) -> None:
        with self._lock:
            self.phase_timings[phase].append(ms)
            self._save()

    @contextmanager
    def timer(self, phase: str) -> Iterator[None]:
        """`with METRICS.timer('fase'): ...` registra i ms trascorsi per quella fase."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record_phase(phase, (time.perf_counter() - start) * 1000.0)

    def snapshot(self) -> dict:
        """Vista read-only per la UI."""
        with self._lock:
            def stats(vals: list[float]) -> dict:
                if not vals:
                    return {"count": 0, "avg_ms": 0.0, "last_ms": 0.0}
                return {
                    "count": len(vals),
                    "avg_ms": round(sum(vals) / len(vals), 1),
                    "last_ms": round(vals[-1], 1),
                }

            total_cache = self.cache_hits + self.cache_misses
            return {
                "intent_counts": dict(self.intent_counts),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_ratio": round(self.cache_hits / total_cache, 3)
                if total_cache
                else 0.0,
                "errors": dict(self.errors),
                "phases": {p: stats(v) for p, v in self.phase_timings.items()},
            }

    def reset(self) -> None:
        with self._lock:
            self.intent_counts.clear()
            self.cache_hits = 0
            self.cache_misses = 0
            self.errors.clear()
            self.phase_timings.clear()
            try:
                _MET_FILE.unlink(missing_ok=True)
            except Exception:
                pass


# Singleton di processo, ripristinato dal file all'avvio.
METRICS = Metrics()
METRICS.load()
