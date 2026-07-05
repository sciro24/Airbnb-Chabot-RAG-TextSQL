"""Observability in-memory: timing per fase, contatori intent, cache hit/miss.

Nessun processo/sink esterno: la sidebar Streamlit legge `snapshot()`.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Metrics:
    """Contatori + timing per fase, thread-safe, in memoria."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    intent_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cache_hits: int = 0
    cache_misses: int = 0
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # fase -> lista di durate in ms
    phase_timings: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def record_intent(self, intent: str) -> None:
        with self._lock:
            self.intent_counts[intent] += 1

    def record_cache(self, hit: bool) -> None:
        with self._lock:
            if hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1

    def record_error(self, where: str) -> None:
        with self._lock:
            self.errors[where] += 1

    def record_phase(self, phase: str, ms: float) -> None:
        with self._lock:
            self.phase_timings[phase].append(ms)

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


# Process-wide singleton.
METRICS = Metrics()
