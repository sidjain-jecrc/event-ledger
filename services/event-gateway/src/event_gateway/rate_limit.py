import time
from math import ceil
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = max(1, window_seconds)
        self.clock = clock or time.monotonic
        self._lock = Lock()
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitDecision:
        now = self.clock()
        cutoff = now - self.window_seconds

        with self._lock:
            request_times = self._requests[key]
            while request_times and request_times[0] <= cutoff:
                request_times.popleft()

            if len(request_times) >= self.max_requests:
                retry_after = ceil(
                    max(1, request_times[0] + self.window_seconds - now)
                )
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after,
                )

            request_times.append(now)
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
