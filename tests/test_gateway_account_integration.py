import httpx
from fastapi.testclient import TestClient

from account_service.config import Settings as AccountSettings
from account_service.main import create_app as create_account_app
from event_gateway.account_client import HttpAccountApplier
from event_gateway.config import Settings as GatewaySettings
from event_gateway.main import create_app as create_gateway_app


def event_payload(
    event_id="evt-001",
    event_type="CREDIT",
    amount=150.00,
):
    return {
        "eventId": event_id,
        "accountId": "acct-123",
        "type": event_type,
        "amount": amount,
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
        "metadata": {
            "source": "integration-test",
        },
    }


def account_service_transport(
    account_client: TestClient,
    observed_trace_ids: list[str] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if observed_trace_ids is not None:
            observed_trace_ids.append(request.headers.get("X-Trace-Id"))

        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query.decode('utf-8')}"

        response = account_client.request(
            request.method,
            path,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    return httpx.MockTransport(handler)


def test_gateway_submit_event_applies_transaction_to_account_service(tmp_path):
    account_settings = AccountSettings(
        service_name="account-service",
        database_url=f"sqlite:///{tmp_path / 'account_service.db'}",
    )
    gateway_settings = GatewaySettings(
        service_name="event-gateway",
        database_url=f"sqlite:///{tmp_path / 'event_gateway.db'}",
        account_service_url="http://account-service:8001",
        account_service_timeout_seconds=2.0,
        account_service_retry_attempts=3,
    )

    account_app = create_account_app(account_settings)
    observed_trace_ids = []
    with TestClient(account_app) as account_client:
        account_http_client = httpx.Client(
            transport=account_service_transport(account_client, observed_trace_ids)
        )
        account_applier = HttpAccountApplier(
            gateway_settings,
            client=account_http_client,
        )
        gateway_app = create_gateway_app(gateway_settings, account_applier)

        with TestClient(gateway_app) as gateway_client:
            first_response = gateway_client.post(
                "/events",
                json=event_payload(),
                headers={"X-Trace-Id": "trace-integration-123"},
            )
            duplicate_response = gateway_client.post(
                "/events",
                json=event_payload(event_type="DEBIT", amount=999.00),
            )
            balance_response = account_client.get("/accounts/acct-123/balance")
            account_response = account_client.get("/accounts/acct-123")

    assert first_response.status_code == 201
    assert first_response.headers["X-Trace-Id"] == "trace-integration-123"
    assert duplicate_response.status_code == 200
    assert duplicate_response.json() == first_response.json()
    assert balance_response.status_code == 200
    assert balance_response.json() == {
        "accountId": "acct-123",
        "balance": 150,
        "currency": "USD",
    }
    assert account_response.status_code == 200
    assert account_response.json()["transactionCount"] == 1
    assert observed_trace_ids == ["trace-integration-123"]
