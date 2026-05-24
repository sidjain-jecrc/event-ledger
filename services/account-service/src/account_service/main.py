from datetime import UTC, datetime
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status

from account_service.config import Settings, get_settings
from account_service.metrics import Metrics
from account_service.schemas import TransactionRequest
from account_service.storage import (
    AccountNotFoundError,
    AccountRepository,
    CurrencyMismatchError,
    decimal_to_json_number,
)


TRACE_HEADER = "X-Trace-Id"

logger = logging.getLogger("account_service")
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    repository = AccountRepository(settings.database_url)
    repository.initialize()
    metrics = Metrics()

    app = FastAPI(title="Account Service", version="0.1.0")
    app.state.settings = settings
    app.state.repository = repository
    app.state.metrics = metrics

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or str(uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)

        metrics.record_request(request.method, route_path, response.status_code)
        response.headers[TRACE_HEADER] = trace_id

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
            },
        }

    @app.get("/metrics")
    def get_metrics() -> Response:
        return Response(
            content=metrics.to_prometheus(settings.service_name),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.post("/accounts/{accountId}/transactions", status_code=status.HTTP_201_CREATED)
    def apply_transaction(
        accountId: str,
        transaction: TransactionRequest,
        response: Response,
    ) -> dict[str, object]:
        try:
            result = repository.apply_transaction(accountId, transaction)
        except CurrencyMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        if not result.created:
            response.status_code = status.HTTP_200_OK

        return {
            **result.transaction,
            "idempotent": not result.created,
            "balance": {
                "accountId": result.transaction["accountId"],
                "balance": decimal_to_json_number(result.balance),
                "currency": result.transaction["currency"],
            },
        }

    @app.get("/accounts/{accountId}/balance")
    def get_balance(accountId: str) -> dict[str, object]:
        try:
            return repository.get_balance(accountId)
        except AccountNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.get("/accounts/{accountId}")
    def get_account(accountId: str) -> dict[str, object]:
        try:
            return repository.get_account(accountId)
        except AccountNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    return app


app = create_app()
