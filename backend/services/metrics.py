"""
Lightweight metrics registry — emits Prometheus-compatible text without
pulling in `prometheus_client` as a dependency.

Why home-grown
──────────────
The full Prometheus client ships ~300KB of code we don't need yet.  All we
want right now is monotonic counters with labels, and a serializer that
returns the standard exposition format.  ~50 lines, fully tested, easy to
later swap for the real thing if we adopt histograms / summaries.

Usage
─────
    from backend.services.metrics import REGISTRY

    REGISTRY.inc("analyses_total", labels={"sector": sector})
    REGISTRY.inc("alerts_fired_total", labels={"condition": cond})

    # Expose at /metrics:
    return Response(REGISTRY.render(), media_type="text/plain; version=0.0.4")
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Optional, Tuple


# Internal key: a frozen tuple of (label_name, label_value) pairs (sorted).
_LabelKey = Tuple[Tuple[str, str], ...]


def _label_key(labels: Optional[Dict[str, str]]) -> _LabelKey:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


class MetricRegistry:
    """Threadsafe in-memory counter store."""

    def __init__(self) -> None:
        # name → label_key → value
        self._counters: Dict[str, Dict[_LabelKey, float]] = defaultdict(dict)
        # name → help text
        self._help: Dict[str, str] = {}
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def describe(self, name: str, help_text: str) -> None:
        """Register a help string.  Idempotent."""
        with self._lock:
            self._help.setdefault(name, help_text)

    def inc(self, name: str, value: float = 1.0,
            labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a labelled counter.  Initialises on first use."""
        key = _label_key(labels)
        with self._lock:
            self._counters[name][key] = self._counters[name].get(key, 0.0) + value

    def get(self, name: str,
            labels: Optional[Dict[str, str]] = None) -> float:
        """Read the current value (mostly used by tests)."""
        return self._counters.get(name, {}).get(_label_key(labels), 0.0)

    def reset(self) -> None:
        """Wipe all counters — only used in tests."""
        with self._lock:
            self._counters.clear()
            self._help.clear()

    def render(self) -> str:
        """
        Emit Prometheus text-exposition v0.0.4.

            # HELP analyses_total ...
            # TYPE analyses_total counter
            analyses_total{sector="Tech"} 12
            analyses_total{sector="Finance"} 7
        """
        lines: list[str] = []
        with self._lock:
            for name, by_label in sorted(self._counters.items()):
                if name in self._help:
                    lines.append(f"# HELP {name} {self._help[name]}")
                lines.append(f"# TYPE {name} counter")
                for label_key, value in by_label.items():
                    if label_key:
                        rendered_labels = ",".join(
                            f'{k}="{_escape(v)}"' for k, v in label_key
                        )
                        lines.append(f"{name}{{{rendered_labels}}} {value:g}")
                    else:
                        lines.append(f"{name} {value:g}")
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    """Escape per Prometheus text format spec."""
    return (
        value.replace("\\", "\\\\")
             .replace("\n", "\\n")
             .replace('"', '\\"')
    )


# ── Singleton + canonical metric definitions ──────────────────────────────────

REGISTRY = MetricRegistry()

# Centralise metric names + help strings — keeps the universe of metrics
# discoverable in one place and prevents typo'd metric proliferation.
REGISTRY.describe("analyses_total",
                  "Number of /companies/analyze invocations.")
REGISTRY.describe("alerts_fired_total",
                  "Alert dispatches by condition.")
REGISTRY.describe("ml_predictions_total",
                  "Number of /ml/predict invocations.")
REGISTRY.describe("ml_trainings_total",
                  "Number of model retrains (success or failure).")
REGISTRY.describe("scheduler_runs_total",
                  "Scheduler job firings by job name.")
REGISTRY.describe("websocket_connections_total",
                  "Cumulative WebSocket clients accepted.")
