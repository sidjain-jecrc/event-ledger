import httpx
import pytest

from event_gateway.account_client import AccountApplicationError, HttpAccountApplier
from event_gateway.config import Settings
from event_gateway.metrics import Metrics
from event_gateway.schemas import EventRequest


def gateway_settings(
    retry_attempts=3,
    retry_backoff_seconds=0.0,
) -> Settings:
    return Settings(
        service_name="event-gateway",
        database_url="sqlite:///:memory:",
        account_service_url="http://account-service:8001",
        account_service_timeout_seconds=2.0,
        account_service_retry_attempts=retry_attempts,
        account_service_retry_backoff_seconds=retry_backoff_seconds,
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
        observed["trace_id"] = request.headers.get("X-Trace-Id")
        observed["body"] = request.read()
        return httpx.Response(201, json={"status": "ok"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    applier.apply_event(event_request(), trace_id="trace-client-123")

    assert observed["method"] == "POST"
    assert observed["path"] == "/accounts/acct-123/transactions"
    assert observed["trace_id"] == "trace-client-123"
    assert observed["body"] == (
        b'{"eventId":"evt-001","type":"CREDIT","amount":150,'
        b'"currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z",'
        b'"metadata":{"source":"test-suite"}}'
    )


def test_http_account_applier_gets_balance_from_account_service_with_trace_id():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["trace_id"] = request.headers.get("X-Trace-Id")
        return httpx.Response(
            200,
            json={
                "accountId": "acct-123",
                "balance": 150,
                "currency": "USD",
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    response = applier.get_balance("acct-123", trace_id="trace-balance-123")

    assert observed["method"] == "GET"
    assert observed["path"] == "/accounts/acct-123/balance"
    assert observed["trace_id"] == "trace-balance-123"
    assert response == {
        "accountId": "acct-123",
        "balance": 150,
        "currency": "USD",
    }


def test_http_account_applier_gets_account_details_from_account_service_with_trace_id():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["trace_id"] = request.headers.get("X-Trace-Id")
        return httpx.Response(
            200,
            json={
                "accountId": "acct-123",
                "currency": "USD",
                "balance": 150,
                "transactionCount": 1,
                "recentTransactions": [],
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    response = applier.get_account("acct-123", trace_id="trace-account-123")

    assert observed["method"] == "GET"
    assert observed["path"] == "/accounts/acct-123"
    assert observed["trace_id"] == "trace-account-123"
    assert response["accountId"] == "acct-123"
    assert response["transactionCount"] == 1


def test_http_account_applier_retries_request_errors_before_returning_503():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=3),
        client=client,
    )

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.apply_event(event_request())

    assert attempts == 3
    assert exc_info.value.status_code == 503
    assert str(exc_info.value) == "Account Service is unavailable"


def test_http_account_applier_balance_request_error_returns_unreachable_message():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=1),
        client=client,
    )

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.get_balance("acct-123")

    assert exc_info.value.status_code == 503
    assert str(exc_info.value) == "Account Service is unreachable"


def test_http_account_applier_uses_exponential_backoff_between_retries():
    attempts = 0
    observed_delays = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(201, json={"status": "ok"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=3, retry_backoff_seconds=0.25),
        client=client,
        sleep=observed_delays.append,
    )

    applier.apply_event(event_request())

    assert attempts == 3
    assert observed_delays == [0.25, 0.5]


def test_http_account_applier_retries_retryable_status_codes():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                json={"detail": "warming up"},
                request=request,
            )
        return httpx.Response(201, json={"status": "ok"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=2),
        client=client,
    )

    applier.apply_event(event_request())

    assert attempts == 2


def test_http_account_applier_records_account_service_call_metrics():
    attempts = 0
    metrics = Metrics()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                json={"detail": "warming up"},
                request=request,
            )
        return httpx.Response(201, json={"status": "ok"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=2),
        client=client,
        metrics=metrics,
    )

    applier.apply_event(event_request())

    snapshot = metrics.snapshot()
    assert snapshot["accountServiceCalls"]["outcomes"] == {
        "503": 1,
        "201": 1,
    }
    assert snapshot["accountServiceCalls"]["latencyMs"]["count"] == 2
    assert snapshot["accountServiceCalls"]["latencyMs"]["total"] >= 0


def test_http_account_applier_returns_503_after_retryable_status_exhausted():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            500,
            json={"detail": "database unavailable"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(
        gateway_settings(retry_attempts=2),
        client=client,
    )

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.apply_event(event_request())

    assert attempts == 2
    assert exc_info.value.status_code == 503
    assert str(exc_info.value) == "Account Service is unavailable"


def test_http_account_applier_preserves_account_service_error_status_and_detail():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
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
    assert attempts == 1


def test_http_account_applier_preserves_account_query_error_status_and_detail():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            404,
            json={"detail": "Account acct-123 was not found"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    applier = HttpAccountApplier(gateway_settings(), client=client)

    with pytest.raises(AccountApplicationError) as exc_info:
        applier.get_account("acct-123")

    assert exc_info.value.status_code == 404
    assert str(exc_info.value) == "Account acct-123 was not found"
    assert attempts == 1
