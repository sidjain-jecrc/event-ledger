from datetime import UTC, datetime
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response, status

from event_gateway.account_client import (
    AccountApplicationError,
    AccountApplier,
    HttpAccountApplier,
)
from event_gateway.config import Settings, get_settings
from event_gateway.metrics import Metrics
from event_gateway.schemas import EventRequest
from event_gateway.storage import EventAlreadyExistsError, EventRepository


TRACE_HEADER = "X-Trace-Id"

logger = logging.getLogger("event_gateway")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_event(
    *,
    level: str,
    service: str,
    trace_id: str,
    message: str,
    **fields: object,
) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "level": level,
        "service": service,
        "traceId": trace_id,
        "message": message,
        **fields,
    }
    logger.log(logging.getLevelName(level), json.dumps(payload, sort_keys=True))


def create_app(
    settings: Settings | None = None,
    account_applier: AccountApplier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = EventRepository(settings.database_url)
    repository.initialize()
    metrics = Metrics()
    account_applier = account_applier or HttpAccountApplier(settings, metrics=metrics)

    app = FastAPI(title="Event Gateway API", version="0.1.0")
    app.state.settings = settings
    app.state.repository = repository
    app.state.account_applier = account_applier
    app.state.metrics = metrics

    @app.middleware("http")
    async def trace_and_log_request(request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or str(uuid4())
        request.state.trace_id = trace_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)

        response.headers[TRACE_HEADER] = trace_id
        metrics.record_request(request.method, route_path, response.status_code)
        log_event(
            level="INFO",
            service=settings.service_name,
            trace_id=trace_id,
            message="request completed",
            method=request.method,
            path=route_path,
            statusCode=response.status_code,
            durationMs=duration_ms,
        )
        return response

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

    @app.get("/metrics")
    def get_metrics() -> dict[str, object]:
        return {
            "service": settings.service_name,
            **metrics.snapshot(),
        }

    @app.post("/events", status_code=status.HTTP_201_CREATED)
    def submit_event(
        event: EventRequest,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        existing_event = repository.get_event(event.event_id)
        if existing_event is not None:
            response.status_code = status.HTTP_200_OK
            return existing_event

        try:
            account_applier.apply_event(event, request.state.trace_id)
            record = repository.create_event(event)
        except AccountApplicationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
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

    @app.get("/accounts/{accountId}/balance")
    def get_account_balance(accountId: str, request: Request) -> dict[str, object]:
        try:
            return account_applier.get_balance(accountId, request.state.trace_id)
        except AccountApplicationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc

    @app.get("/accounts/{accountId}")
    def get_account(accountId: str, request: Request) -> dict[str, object]:
        try:
            return account_applier.get_account(accountId, request.state.trace_id)
        except AccountApplicationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc

    return app


app = create_app()
