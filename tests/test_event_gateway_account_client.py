import httpx
import pytest

from event_gateway.account_client import AccountApplicationError, HttpAccountApplier
from event_gateway.config import Settings
from event_gateway.schemas import EventRequest


def gateway_settings() -> Settings:
    return Settings(
        service_name="event-gateway",
        database_url="sqlite:///:memory:",
        account_service_url="http://account-service:8001",
        account_service_timeout_seconds=2.0,
        account_service_retry_attempts=3,
    )


def event_request() -> EventRequest:
    return EventRequest.model_validate(
        {
            "eventId": "evt-001",
            "accountId": "acct-123",
            "type": "CREDIT",
            "amount": 150.00,
            "currency": "USD",
            "eventTimestamp": "2026-05-15T14:02:11Z",
            "metadata": {
                "source": "test-suite",
            },
        }
    )


def test_http_account_applier_posts_gateway_event_to_account_service_contract():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["body"] = request.read()
        return httpx.Response(201, json={"status": "ok"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    applier.apply_event(event_request())

    assert observed["method"] == "POST"
    assert observed["path"] == "/accounts/acct-123/transactions"
    assert observed["body"] == (
        b'{"eventId":"evt-001","type":"CREDIT","amount":150,'
        b'"currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z",'
        b'"metadata":{"source":"test-suite"}}'
    )


def test_http_account_applier_maps_request_errors_to_503():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.apply_event(event_request())

    assert exc_info.value.status_code == 503
    assert str(exc_info.value) == "Account Service is unavailable"


def test_http_account_applier_preserves_account_service_error_status_and_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": "Account acct-123 already uses USD"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.apply_event(event_request())

    assert exc_info.value.status_code == 409
    assert str(exc_info.value) == "Account acct-123 already uses USD"
