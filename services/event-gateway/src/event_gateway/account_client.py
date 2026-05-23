from datetime import UTC
from decimal import Decimal
import time
from collections.abc import Callable
from typing import Protocol
from urllib.parse import quote

import httpx

from event_gateway.config import Settings
from event_gateway.metrics import Metrics
from event_gateway.schemas import EventRequest


class AccountApplicationError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 503,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccountApplier(Protocol):
    def apply_event(self, event: EventRequest, trace_id: str | None = None) -> None:
        pass


class NoopAccountApplier:
    def apply_event(self, event: EventRequest, trace_id: str | None = None) -> None:
        return None


def decimal_to_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def account_transaction_payload(event: EventRequest) -> dict[str, object]:
    event_timestamp = event.event_timestamp.astimezone(UTC)
    return {
        "eventId": event.event_id,
        "type": event.type,
        "amount": decimal_to_json_number(event.amount),
        "currency": event.currency,
        "eventTimestamp": event_timestamp.isoformat().replace("+00:00", "Z"),
        "metadata": event.metadata,
    }


class HttpAccountApplier:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.base_url = settings.account_service_url.rstrip("/")
        self.timeout_seconds = settings.account_service_timeout_seconds
        self.retry_attempts = max(1, settings.account_service_retry_attempts)
        self.retry_backoff_seconds = max(
            0.0,
            settings.account_service_retry_backoff_seconds,
        )
        self.client = client or httpx.Client(timeout=self.timeout_seconds)
        self.sleep = sleep or time.sleep
        self.metrics = metrics

    def apply_event(self, event: EventRequest, trace_id: str | None = None) -> None:
        account_id = quote(event.account_id, safe="")
        url = f"{self.base_url}/accounts/{account_id}/transactions"
        payload = account_transaction_payload(event)
        headers = {"X-Trace-Id": trace_id} if trace_id else None

        last_error: httpx.RequestError | None = None
        last_response: httpx.Response | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                start = time.perf_counter()
                response = self.client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except httpx.RequestError as exc:
                self._record_account_service_call(
                    outcome="request_error",
                    start=start,
                )
                last_error = exc
                if attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise AccountApplicationError(
                    "Account Service is unavailable",
                    status_code=503,
                ) from exc

            self._record_account_service_call(
                outcome=str(response.status_code),
                start=start,
            )

            if 200 <= response.status_code < 300:
                return

            if not _should_retry_response(response):
                raise AccountApplicationError(
                    _error_detail(response),
                    status_code=response.status_code,
                )

            last_response = response
            if attempt < self.retry_attempts:
                self._sleep_before_retry(attempt)
                continue

        if last_response is not None:
            raise AccountApplicationError(
                "Account Service is unavailable",
                status_code=503,
            )

        raise AccountApplicationError(
            "Account Service is unavailable",
            status_code=503,
        ) from last_error

    def _sleep_before_retry(self, completed_attempt: int) -> None:
        delay = self.retry_backoff_seconds * (2 ** (completed_attempt - 1))
        if delay > 0:
            self.sleep(delay)

    def _record_account_service_call(self, *, outcome: str, start: float) -> None:
        if self.metrics is None:
            return
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        self.metrics.record_account_service_call(
            outcome=outcome,
            latency_ms=latency_ms,
        )


def _should_retry_response(response: httpx.Response) -> bool:
    return response.status_code in (408, 429) or response.status_code >= 500


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or "Account Service rejected the transaction"

    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    return "Account Service rejected the transaction"
