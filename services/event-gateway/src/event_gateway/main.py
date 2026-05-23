from fastapi import FastAPI

from event_gateway.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Event Gateway API", version="0.1.0")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "diagnostics": {
                "database": "not_initialized",
                "accountServiceUrl": settings.account_service_url,
            },
        }

    return app


app = create_app()
