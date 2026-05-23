from datetime import UTC
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote

import httpx

from event_gateway.config import Settings
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
    def apply_event(self, event: EventRequest) -> None:
        pass


class NoopAccountApplier:
    def apply_event(self, event: EventRequest) -> None:
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
    ) -> None:
        self.base_url = settings.account_service_url.rstrip("/")
        self.timeout_seconds = settings.account_service_timeout_seconds
        self.client = client or httpx.Client(timeout=self.timeout_seconds)

    def apply_event(self, event: EventRequest) -> None:
        account_id = quote(event.account_id, safe="")
        url = f"{self.base_url}/accounts/{account_id}/transactions"
        payload = account_transaction_payload(event)

        try:
            response = self.client.post(
                url,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise AccountApplicationError(
                "Account Service is unavailable",
                status_code=503,
            ) from exc

        if 200 <= response.status_code < 300:
            return

        raise AccountApplicationError(
            _error_detail(response),
            status_code=response.status_code,
        )


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or "Account Service rejected the transaction"

    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    return "Account Service rejected the transaction"
