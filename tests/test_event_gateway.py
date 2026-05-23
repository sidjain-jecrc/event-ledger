import pytest
from fastapi.testclient import TestClient

from event_gateway.account_client import AccountApplicationError
from event_gateway.config import Settings
from event_gateway.main import create_app


class RecordingAccountApplier:
    def __init__(self) -> None:
        self.events = []

    def apply_event(self, event) -> None:
        self.events.append(event)


class FailingAccountApplier:
    def apply_event(self, event) -> None:
        raise AccountApplicationError("Account Service is unavailable")


class ToggleAccountApplier:
    def __init__(self) -> None:
        self.available = True

    def apply_event(self, event) -> None:
        if not self.available:
            raise AccountApplicationError("Account Service is unavailable")


@pytest.fixture
def gateway_settings(tmp_path):
    return Settings(
        service_name="event-gateway",
        database_url=f"sqlite:///{tmp_path / 'event_gateway.db'}",
        account_service_url="http://account-service:8001",
        account_service_timeout_seconds=2.0,
        account_service_retry_attempts=3,
    )


@pytest.fixture
def applier():
    return RecordingAccountApplier()


@pytest.fixture
def client(gateway_settings, applier):
    return TestClient(create_app(gateway_settings, account_applier=applier))


def event_payload(
    event_id="evt-001",
    account_id="acct-123",
    event_type="CREDIT",
    amount=150.00,
    timestamp="2026-05-15T14:02:11Z",
):
    return {
        "eventId": event_id,
        "accountId": account_id,
        "type": event_type,
        "amount": amount,
        "currency": "USD",
        "eventTimestamp": timestamp,
        "metadata": {
            "source": "test-suite",
        },
    }


def test_submits_event_and_stores_it_locally(client, applier):
    response = client.post("/events", json=event_payload())

    assert response.status_code == 201
    assert response.json() == {
        "eventId": "evt-001",
        "accountId": "acct-123",
        "type": "CREDIT",
        "amount": 150,
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
        "metadata": {
            "source": "test-suite",
        },
        "status": "ACCEPTED",
    }
    assert [event.event_id for event in applier.events] == ["evt-001"]

    read_response = client.get("/events/evt-001")

    assert read_response.status_code == 200
    assert read_response.json() == response.json()


def test_duplicate_event_returns_original_and_does_not_call_account_again(client, applier):
    first_response = client.post("/events", json=event_payload())

    changed_payload = event_payload(amount=999, event_type="DEBIT")
    duplicate_response = client.post("/events", json=changed_payload)

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 200
    assert duplicate_response.json() == first_response.json()
    assert [event.event_id for event in applier.events] == ["evt-001"]


def test_lists_events_for_account_by_event_timestamp(client):
    client.post(
        "/events",
        json=event_payload(
            event_id="evt-late",
            timestamp="2026-05-15T16:02:11Z",
        ),
    )
    client.post(
        "/events",
        json=event_payload(
            event_id="evt-early",
            timestamp="2026-05-15T14:02:11Z",
        ),
    )
    client.post(
        "/events",
        json=event_payload(
            event_id="evt-other-account",
            account_id="acct-999",
            timestamp="2026-05-15T13:02:11Z",
        ),
    )

    response = client.get("/events", params={"account": "acct-123"})

    assert response.status_code == 200
    assert response.json()["accountId"] == "acct-123"
    assert [event["eventId"] for event in response.json()["events"]] == [
        "evt-early",
        "evt-late",
    ]


def test_get_missing_event_returns_404(client):
    response = client.get("/events/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Event missing was not found"


@pytest.mark.parametrize(
    ("payload_update", "expected_field"),
    [
        ({"accountId": ""}, "accountId"),
        ({"amount": 0}, "amount"),
        ({"type": "TRANSFER"}, "type"),
        ({"eventTimestamp": "2026-05-15T14:02:11"}, "eventTimestamp"),
    ],
)
def test_rejects_invalid_event_payloads(client, payload_update, expected_field):
    payload = event_payload()
    payload.update(payload_update)

    response = client.post("/events", json=payload)

    assert response.status_code == 422
    error_fields = {
        str(location[-1])
        for error in response.json()["detail"]
        for location in [error["loc"]]
    }
    assert expected_field in error_fields


def test_requires_account_query_parameter(client):
    response = client.get("/events")

    assert response.status_code == 422


def test_does_not_store_event_when_account_application_fails(gateway_settings):
    client = TestClient(
        create_app(gateway_settings, account_applier=FailingAccountApplier())
    )

    response = client.post("/events", json=event_payload())
    read_response = client.get("/events/evt-001")

    assert response.status_code == 503
    assert response.json()["detail"] == "Account Service is unavailable"
    assert read_response.status_code == 404


def test_existing_event_reads_still_work_when_account_application_fails(gateway_settings):
    applier = ToggleAccountApplier()
    client = TestClient(create_app(gateway_settings, account_applier=applier))

    accepted_response = client.post("/events", json=event_payload())
    applier.available = False
    failed_response = client.post(
        "/events",
        json=event_payload(event_id="evt-002"),
    )
    read_response = client.get("/events/evt-001")
    list_response = client.get("/events", params={"account": "acct-123"})

    assert accepted_response.status_code == 201
    assert failed_response.status_code == 503
    assert read_response.status_code == 200
    assert read_response.json() == accepted_response.json()
    assert list_response.status_code == 200
    assert [event["eventId"] for event in list_response.json()["events"]] == [
        "evt-001"
    ]


def test_gateway_health_reports_database_and_account_service_url(gateway_settings):
    client = TestClient(create_app(gateway_settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "event-gateway",
        "diagnostics": {
            "database": "ok",
            "accountServiceUrl": "http://account-service:8001",
        },
    }
