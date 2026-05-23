from account_service.main import create_app as create_account_service_app
from event_gateway.main import create_app as create_event_gateway_app
from fastapi.testclient import TestClient


def route_paths(app):
    return {route.path for route in app.routes}


def test_account_service_app_factory_exposes_health_route():
    app = create_account_service_app()

    assert app.title == "Account Service"
    assert app.state.settings.service_name == "account-service"
    assert "/health" in route_paths(app)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "account-service",
        "diagnostics": {
            "database": "not_initialized",
        },
    }


def test_event_gateway_app_factory_exposes_health_route_and_defaults():
    app = create_event_gateway_app()

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
