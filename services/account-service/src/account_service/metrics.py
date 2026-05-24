from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()

    def record_request(self, method: str, route: str, status_code: int) -> None:
        key = (method, route, status_code)
        with self._lock:
            self._requests[key] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                f"{method} {route} {status_code}": count
                for (method, route, status_code), count in self._requests.items()
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
            return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    return ",".join(f'{key}="{_escape_label(value)}"' for key, value in values.items())


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
