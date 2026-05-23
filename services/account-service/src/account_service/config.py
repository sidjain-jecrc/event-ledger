from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("ACCOUNT_SERVICE_NAME", "account-service"),
        database_url=os.getenv(
            "ACCOUNT_SERVICE_DATABASE_URL",
            "sqlite:///./account_service.db",
        ),
    )
