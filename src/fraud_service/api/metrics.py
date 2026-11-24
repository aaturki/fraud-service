"""Prometheus metrics with no new dependency: a request counter, a latency histogram,
decisions served and the model in use, rendered in the text exposition format.

Each uvicorn worker keeps its own numbers, as the Prometheus client does without its
multiprocess mode: a scrape reads one worker. Labels are route templates, never raw paths,
so a scanner hitting random URLs cannot create unbounded series.
"""
import threading
from collections import defaultdict
from collections.abc import Iterable

# Seconds. Scoring takes a few milliseconds, so the low end is where the detail matters.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()      # decisions are counted from worker threads
        self._requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._buckets: dict[str, list[int]] = {}
        self._sum: dict[str, float] = defaultdict(float)
        self._count: dict[str, int] = defaultdict(int)
        self._decisions: dict[str, int] = defaultdict(int)

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self._requests[(method, route, str(status))] += 1
            counts = self._buckets.setdefault(route, [0] * len(BUCKETS))
            for i, upper in enumerate(BUCKETS):
                if seconds <= upper:
                    counts[i] += 1
            self._sum[route] += seconds
            self._count[route] += 1

    def count_decisions(self, decisions: Iterable[str]) -> None:
        with self._lock:
            for decision in decisions:
                self._decisions[decision] += 1

    def render(self, model_version: str | None) -> str:
        with self._lock:
            lines = [
                "# HELP http_requests_total HTTP requests by method, route and status code.",
                "# TYPE http_requests_total counter",
            ]
            for (method, route, status), value in sorted(self._requests.items()):
                lines.append(f'http_requests_total{{method="{method}",route="{route}",'
                             f'status="{status}"}} {value}')
            lines += ["# HELP http_request_duration_seconds Request latency by route.",
                      "# TYPE http_request_duration_seconds histogram"]
            for route in sorted(self._buckets):
                for upper, value in zip(BUCKETS, self._buckets[route], strict=True):
                    lines.append(f'http_request_duration_seconds_bucket{{route="{route}",'
                                 f'le="{upper}"}} {value}')
                lines.append(f'http_request_duration_seconds_bucket{{route="{route}",'
                             f'le="+Inf"}} {self._count[route]}')
                lines.append(f'http_request_duration_seconds_sum{{route="{route}"}} '
                             f"{self._sum[route]:.6f}")
                lines.append(f'http_request_duration_seconds_count{{route="{route}"}} '
                             f"{self._count[route]}")
            lines += ["# HELP fraud_decisions_total Decisions served, by outcome.",
                      "# TYPE fraud_decisions_total counter"]
            for decision, value in sorted(self._decisions.items()):
                lines.append(f'fraud_decisions_total{{decision="{decision}"}} {value}')
            if model_version:
                lines += ["# HELP fraud_model_info The model version this process serves.",
                          "# TYPE fraud_model_info gauge",
                          f'fraud_model_info{{version="{model_version}"}} 1']
            return "\n".join(lines) + "\n"
