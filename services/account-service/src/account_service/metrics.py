from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[str] = Counter()

    def record_request(self, method: str, route: str, status_code: int) -> None:
        key = f"{method} {route} {status_code}"
        with self._lock:
            self._requests[key] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._requests)
