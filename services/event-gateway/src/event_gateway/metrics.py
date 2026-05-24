from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._account_service_calls: Counter[str] = Counter()
        self._account_service_latency_total_ms = 0.0
        self._account_service_latency_max_ms = 0.0

    def record_request(self, method: str, route: str, status_code: int) -> None:
        key = (method, route, status_code)
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
                "requests": {
                    f"{method} {route} {status_code}": count
                    for (method, route, status_code), count in self._requests.items()
                },
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

    def to_prometheus(self, service_name: str) -> str:
        with self._lock:
            lines = [
                "# HELP http_requests_total Total HTTP requests.",
                "# TYPE http_requests_total counter",
            ]
            for (method, route, status_code), count in sorted(self._requests.items()):
                labels = _labels(
                    service=service_name,
                    method=method,
                    path=route,
                    status=str(status_code),
                )
                lines.append(f"http_requests_total{{{labels}}} {count}")

            lines.extend(
                [
                    "# HELP account_service_calls_total Total Account Service calls.",
                    "# TYPE account_service_calls_total counter",
                ]
            )
            for outcome, count in sorted(self._account_service_calls.items()):
                labels = _labels(service=service_name, outcome=outcome)
                lines.append(f"account_service_calls_total{{{labels}}} {count}")

            account_call_count = sum(self._account_service_calls.values())
            latency_total_seconds = self._account_service_latency_total_ms / 1000
            latency_max_seconds = self._account_service_latency_max_ms / 1000
            latency_labels = _labels(service=service_name)

            lines.extend(
                [
                    "# HELP account_service_call_latency_seconds Account Service call latency.",
                    "# TYPE account_service_call_latency_seconds summary",
                    (
                        "account_service_call_latency_seconds_count"
                        f"{{{latency_labels}}} {account_call_count}"
                    ),
                    (
                        "account_service_call_latency_seconds_sum"
                        f"{{{latency_labels}}} {latency_total_seconds:.6f}"
                    ),
                    (
                        "account_service_call_latency_seconds_max"
                        f"{{{latency_labels}}} {latency_max_seconds:.6f}"
                    ),
                ]
            )

            return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    return ",".join(f'{key}="{_escape_label(value)}"' for key, value in values.items())


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
