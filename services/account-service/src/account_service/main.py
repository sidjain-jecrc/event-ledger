from fastapi import FastAPI

from account_service.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Account Service", version="0.1.0")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "diagnostics": {
                "database": "not_initialized",
            },
        }

    return app


app = create_app()
