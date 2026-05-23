import pytest
from fastapi.testclient import TestClient

from account_service.config import Settings
from account_service.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        service_name="account-service",
        database_url=f"sqlite:///{tmp_path / 'account_service.db'}",
    )
    return TestClient(create_app(settings))


def transaction_payload(
    event_id="evt-001",
    transaction_type="CREDIT",
    amount=150.00,
    timestamp="2026-05-15T14:02:11Z",
):
    return {
        "eventId": event_id,
        "type": transaction_type,
        "amount": amount,
        "currency": "USD",
        "eventTimestamp": timestamp,
        "metadata": {
            "source": "test-suite",
        },
    }


def test_applies_credit_and_debit_transactions_to_balance(client):
    credit_response = client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(),
    )
    debit_response = client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(
            event_id="evt-002",
            transaction_type="DEBIT",
            amount=40.25,
            timestamp="2026-05-15T15:02:11Z",
        ),
    )

    assert credit_response.status_code == 201
    assert credit_response.json()["balance"] == {
        "accountId": "acct-123",
        "balance": 150,
        "currency": "USD",
    }
    assert debit_response.status_code == 201
    assert debit_response.json()["balance"] == {
        "accountId": "acct-123",
        "balance": 109.75,
        "currency": "USD",
    }

    balance_response = client.get("/accounts/acct-123/balance")

    assert balance_response.status_code == 200
    assert balance_response.json() == {
        "accountId": "acct-123",
        "balance": 109.75,
        "currency": "USD",
    }


def test_duplicate_event_id_is_idempotent_and_does_not_change_balance(client):
    first_response = client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(),
    )
    duplicate_response = client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(),
    )

    assert first_response.status_code == 201
    assert first_response.json()["idempotent"] is False
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["idempotent"] is True
    assert duplicate_response.json()["balance"]["balance"] == 150

    account_response = client.get("/accounts/acct-123")

    assert account_response.status_code == 200
    assert account_response.json()["transactionCount"] == 1


def test_account_details_include_recent_transactions_in_reverse_timestamp_order(client):
    client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(
            event_id="evt-late",
            amount=100,
            timestamp="2026-05-15T16:02:11Z",
        ),
    )
    client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(
            event_id="evt-early",
            amount=25,
            timestamp="2026-05-15T14:02:11Z",
        ),
    )

    response = client.get("/accounts/acct-123")

    assert response.status_code == 200
    body = response.json()
    assert body["accountId"] == "acct-123"
    assert body["balance"] == 125
    assert body["transactionCount"] == 2
    assert [tx["eventId"] for tx in body["recentTransactions"]] == [
        "evt-late",
        "evt-early",
    ]


def test_unknown_account_returns_404(client):
    balance_response = client.get("/accounts/missing/balance")
    account_response = client.get("/accounts/missing")

    assert balance_response.status_code == 404
    assert account_response.status_code == 404


@pytest.mark.parametrize(
    ("payload_update", "expected_field"),
    [
        ({"amount": 0}, "amount"),
        ({"type": "TRANSFER"}, "type"),
        ({"eventTimestamp": "2026-05-15T14:02:11"}, "eventTimestamp"),
    ],
)
def test_rejects_invalid_transaction_payloads(client, payload_update, expected_field):
    payload = transaction_payload()
    payload.update(payload_update)

    response = client.post("/accounts/acct-123/transactions", json=payload)

    assert response.status_code == 422
    error_fields = {
        str(location[-1])
        for error in response.json()["detail"]
        for location in [error["loc"]]
    }
    assert expected_field in error_fields


def test_rejects_currency_mismatch_for_existing_account(client):
    client.post(
        "/accounts/acct-123/transactions",
        json=transaction_payload(),
    )
    mismatch_payload = transaction_payload(event_id="evt-002")
    mismatch_payload["currency"] = "EUR"

    response = client.post("/accounts/acct-123/transactions", json=mismatch_payload)

    assert response.status_code == 409
    assert "already uses USD" in response.json()["detail"]


def test_health_metrics_and_trace_header(client):
    health_response = client.get("/health", headers={"X-Trace-Id": "trace-phase-1"})

    assert health_response.status_code == 200
    assert health_response.headers["X-Trace-Id"] == "trace-phase-1"
    assert health_response.json() == {
        "status": "ok",
        "service": "account-service",
        "diagnostics": {
            "database": "ok",
        },
    }

    metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    assert metrics_response.json()["service"] == "account-service"
    assert metrics_response.json()["requests"]["GET /health 200"] == 1
