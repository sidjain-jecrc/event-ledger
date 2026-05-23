from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str
    database_url: str
    account_service_url: str
    account_service_timeout_seconds: float
    account_service_retry_attempts: int
    account_service_retry_backoff_seconds: float = 0.1


def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("EVENT_GATEWAY_NAME", "event-gateway"),
        database_url=os.getenv(
            "EVENT_GATEWAY_DATABASE_URL",
            "sqlite:///./event_gateway.db",
        ),
        account_service_url=os.getenv(
            "ACCOUNT_SERVICE_URL",
            "http://localhost:8001",
        ),
        account_service_timeout_seconds=float(
            os.getenv("ACCOUNT_SERVICE_TIMEOUT_SECONDS", "2.0")
        ),
        account_service_retry_attempts=int(
            os.getenv("ACCOUNT_SERVICE_RETRY_ATTEMPTS", "3")
        ),
        account_service_retry_backoff_seconds=float(
            os.getenv("ACCOUNT_SERVICE_RETRY_BACKOFF_SECONDS", "0.1")
        ),
    )
