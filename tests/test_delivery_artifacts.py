from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_defines_both_services_and_separate_databases():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "account-service:" in compose
    assert "event-gateway:" in compose
    assert "ACCOUNT_SERVICE_URL: http://account-service:8001" in compose
    assert "ACCOUNT_SERVICE_DATABASE_URL: sqlite:////data/account_service.db" in compose
    assert "EVENT_GATEWAY_DATABASE_URL: sqlite:////data/event_gateway.db" in compose
    assert "8001:8001" not in compose
    assert "account-service-data:" in compose
    assert "event-gateway-data:" in compose
    assert "condition: service_healthy" in compose


def test_dockerfile_installs_project_and_exposes_service_ports():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "FROM python:3.13-slim" in dockerfile
    assert "python -m pip install --no-cache-dir ." in dockerfile
    assert "EXPOSE 8000 8001" in dockerfile


def test_readme_documents_docker_compose_and_final_verification():
    readme = (ROOT / "README.md").read_text()

    assert "docker compose up --build" in readme
    assert "http://127.0.0.1:8000/health" in readme
    assert "Account Service is internal" in readme
    assert "docker compose exec account-service" in readme
    assert '"Account Service is unreachable"' in readme
    assert "Final Acceptance Checklist" in readme
