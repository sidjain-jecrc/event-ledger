from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[str] = Counter()
        self._account_service_calls: Counter[str] = Counter()
        self._account_service_latency_total_ms = 0.0
        self._account_service_latency_max_ms = 0.0

    def record_request(self, method: str, route: str, status_code: int) -> None:
        key = f"{method} {route} {status_code}"
        with self._lock:
            self._requests[key] += 1

    def record_account_service_call(
        self,
        *,
        outcome: str,
        latency_ms: float,
    ) -> None:
        with self._lock:
            self._account_service_calls[outcome] += 1
            self._account_service_latency_total_ms += latency_ms
            self._account_service_latency_max_ms = max(
                self._account_service_latency_max_ms,
                latency_ms,
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            account_call_count = sum(self._account_service_calls.values())
            average_latency_ms = (
                self._account_service_latency_total_ms / account_call_count
                if account_call_count
                else 0.0
            )

            return {
                "requests": dict(self._requests),
                "accountServiceCalls": {
                    "outcomes": dict(self._account_service_calls),
                    "latencyMs": {
                        "count": account_call_count,
                        "total": round(self._account_service_latency_total_ms, 2),
                        "average": round(average_latency_ms, 2),
                        "max": round(self._account_service_latency_max_ms, 2),
                    },
                },
            }
