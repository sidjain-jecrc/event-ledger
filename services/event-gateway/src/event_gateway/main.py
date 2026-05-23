from fastapi import FastAPI, HTTPException, Query, Response, status

from event_gateway.account_client import (
    AccountApplicationError,
    AccountApplier,
    NoopAccountApplier,
)
from event_gateway.config import Settings, get_settings
from event_gateway.schemas import EventRequest
from event_gateway.storage import EventAlreadyExistsError, EventRepository


def create_app(
    settings: Settings | None = None,
    account_applier: AccountApplier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = EventRepository(settings.database_url)
    repository.initialize()
    account_applier = account_applier or NoopAccountApplier()

    app = FastAPI(title="Event Gateway API", version="0.1.0")
    app.state.settings = settings
    app.state.repository = repository
    app.state.account_applier = account_applier

    @app.get("/health")
    def health() -> dict[str, object]:
        database_status = "ok" if repository.check_connectivity() else "unavailable"
        return {
            "status": "ok",
            "service": settings.service_name,
            "diagnostics": {
                "database": database_status,
                "accountServiceUrl": settings.account_service_url,
            },
        }

    @app.post("/events", status_code=status.HTTP_201_CREATED)
    def submit_event(event: EventRequest, response: Response) -> dict[str, object]:
        existing_event = repository.get_event(event.event_id)
        if existing_event is not None:
            response.status_code = status.HTTP_200_OK
            return existing_event

        try:
            account_applier.apply_event(event)
            record = repository.create_event(event)
        except AccountApplicationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except EventAlreadyExistsError:
            stored_event = repository.get_event(event.event_id)
            if stored_event is None:
                raise
            response.status_code = status.HTTP_200_OK
            return stored_event

        return record.event

    @app.get("/events")
    def list_events(account: str = Query(..., min_length=1)) -> dict[str, object]:
        return {
            "accountId": account,
            "events": repository.list_events_for_account(account),
        }

    @app.get("/events/{eventId}")
    def get_event(eventId: str) -> dict[str, object]:
        event = repository.get_event(eventId)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {eventId} was not found",
            )
        return event

    return app


app = create_app()
