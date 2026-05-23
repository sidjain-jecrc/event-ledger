from account_service.config import Settings as AccountSettings
from account_service.main import create_app as create_account_service_app
from event_gateway.config import Settings as GatewaySettings
from event_gateway.main import create_app as create_event_gateway_app
from fastapi.testclient import TestClient


def route_paths(app):
    return {route.path for route in app.routes}


def test_account_service_app_factory_exposes_health_route(tmp_path):
    settings = AccountSettings(
        service_name="account-service",
        database_url=f"sqlite:///{tmp_path / 'account_service.db'}",
    )
    app = create_account_service_app(settings)

    assert app.title == "Account Service"
    assert app.state.settings.service_name == "account-service"
    assert "/health" in route_paths(app)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "account-service",
        "diagnostics": {
            "database": "ok",
        },
    }


def test_event_gateway_app_factory_exposes_health_route_and_defaults():
    settings = GatewaySettings(
        service_name="event-gateway",
        database_url="sqlite:///./event_gateway.db",
        account_service_url="http://localhost:8001",
        account_service_timeout_seconds=2.0,
        account_service_retry_attempts=3,
    )
    app = create_event_gateway_app(settings)

    assert app.title == "Event Gateway API"
    assert app.state.settings.service_name == "event-gateway"
    assert app.state.settings.account_service_url == "http://localhost:8001"
    assert "/health" in route_paths(app)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "event-gateway",
        "diagnostics": {
            "database": "not_initialized",
            "accountServiceUrl": "http://localhost:8001",
        },
    }
