# Event Ledger

Event Ledger is a two-service system for processing financial transaction
events. The requirements live in `event-ledger-candidate-handout.md`; review
that document before implementing or marking any feature complete.

## Architecture

- **Event Gateway API**: public-facing FastAPI service that receives events,
  validates requests, stores accepted event records, and calls Account Service.
- **Account Service**: internal FastAPI service that owns account balances and
  transaction history.

The services must run as independent processes and use separate SQLite
databases. They communicate through synchronous REST.

## Current Phase

Phase 5 is distributed tracing and structured Gateway logging:

- Python + FastAPI service skeletons
- dependency and test configuration
- basic app factories
- Account Service SQLite persistence
- Account Service transaction application
- Account Service idempotency by `eventId`
- Account Service balance and account detail endpoints
- Account Service health, metrics, trace header echoing, and structured request
  logs
- Event Gateway SQLite event persistence
- Event Gateway event validation and duplicate detection by `eventId`
- Event Gateway event lookup and account event listing ordered by
  `eventTimestamp`
- Event Gateway real synchronous REST call to Account Service
- Gateway persists accepted events only after Account Service successfully
  applies the transaction
- Gateway Account Service calls use bounded timeout + retry with exponential
  backoff
- Gateway returns `503 Service Unavailable` when Account Service cannot be
  reached
- Gateway local event reads continue to work while Account Service is down
- Gateway accepts or generates `X-Trace-Id` for every request
- Gateway propagates `X-Trace-Id` to Account Service
- Gateway and Account Service both emit JSON request logs with the trace ID

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run Tests

```bash
pytest
```

## Run Services Locally

Account Service:

```bash
uvicorn account_service.main:app --app-dir services/account-service/src --port 8001
```

Event Gateway API:

```bash
uvicorn event_gateway.main:app --app-dir services/event-gateway/src --port 8000
```

## Account Service API

### `POST /accounts/{accountId}/transactions`

Applies a transaction to an account. The Account Service treats `eventId` as an
idempotency key, so duplicate submissions return the original transaction with
`200 OK` and do not change the balance again. New transactions return
`201 Created`.

```json
{
  "eventId": "evt-001",
  "type": "CREDIT",
  "amount": 150.00,
  "currency": "USD",
  "eventTimestamp": "2026-05-15T14:02:11Z",
  "metadata": {
    "source": "mainframe-batch"
  }
}
```

The first transaction establishes the account currency. Later transactions for
the same account with a different currency return `409 Conflict` to avoid
mixing currencies in a single balance.

### `GET /accounts/{accountId}/balance`

Returns the current balance for an existing account.

### `GET /accounts/{accountId}`

Returns account details, balance, transaction count, and recent transactions.
Recent transactions are ordered from newest to oldest by event timestamp.

### `GET /health`

Returns service status and SQLite connectivity diagnostics.

### `GET /metrics`

Returns in-memory request counts by method, route, and status code.

## Event Gateway API

The Gateway applies new events by calling Account Service synchronously over
REST. The Gateway stores an event locally only after Account Service accepts the
transaction. Calls to Account Service use a bounded retry policy with
exponential backoff for transient request errors, timeouts, `408`, `429`, and
`5xx` responses. Gateway does not retry non-transient Account Service `4xx`
responses.

### `POST /events`

Validates and accepts a transaction event into Gateway local storage. New events
return `201 Created` after Account Service applies the transaction. Duplicate
`eventId` submissions return the original stored event with `200 OK` and do not
call Account Service again. If Account Service is unavailable after the retry
policy is exhausted, the Gateway returns `503 Service Unavailable` and does not
store the new event.

```json
{
  "eventId": "evt-001",
  "accountId": "acct-123",
  "type": "CREDIT",
  "amount": 150.00,
  "currency": "USD",
  "eventTimestamp": "2026-05-15T14:02:11Z",
  "metadata": {
    "source": "mainframe-batch"
  }
}
```

Accepted event responses include `status: "ACCEPTED"`.

### `GET /events/{eventId}`

Returns one stored Gateway event, or `404 Not Found` when the event does not
exist.

### `GET /events?account={accountId}`

Returns events for the account from Gateway local storage. Results are ordered
chronologically by `eventTimestamp`.

### `GET /health`

Returns Gateway service status, SQLite connectivity diagnostics, and configured
Account Service URL.

## Resiliency Configuration

The Gateway Account Service client is configured with environment variables:

- `ACCOUNT_SERVICE_TIMEOUT_SECONDS`: per-attempt timeout, default `2.0`.
- `ACCOUNT_SERVICE_RETRY_ATTEMPTS`: total attempts, default `3`.
- `ACCOUNT_SERVICE_RETRY_BACKOFF_SECONDS`: initial retry backoff, default `0.1`.

Backoff doubles between attempts. For example, with the default backoff and
three total attempts, retries wait about `0.1s` and then `0.2s`.

## Tracing And Logs

Both services use `X-Trace-Id` as the trace header.

- If a client sends `X-Trace-Id` to Gateway, Gateway returns the same value in
  its response and propagates it to Account Service.
- If a client omits `X-Trace-Id`, Gateway generates one and returns it in the
  response.
- Gateway and Account Service emit JSON request logs with `timestamp`, `level`,
  `service`, `traceId`, `message`, `method`, `path`, `statusCode`, and
  `durationMs`.

Example log:

```json
{
  "durationMs": 25.82,
  "level": "INFO",
  "message": "request completed",
  "method": "POST",
  "path": "/events",
  "service": "event-gateway",
  "statusCode": 201,
  "timestamp": "2026-05-23T23:03:43.698452Z",
  "traceId": "manual-phase5-trace"
}
```

## Phase 5 Verification

Automated verification:

```bash
pytest
```

Manual verification example:

```bash
uvicorn account_service.main:app --app-dir services/account-service/src --port 8001
curl -H "X-Trace-Id: manual-phase-1" http://127.0.0.1:8001/health
curl -X POST http://127.0.0.1:8001/accounts/acct-123/transactions \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: manual-phase-1" \
  -d '{"eventId":"evt-001","type":"CREDIT","amount":150.00,"currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z","metadata":{"source":"manual"}}'
curl http://127.0.0.1:8001/accounts/acct-123/balance
curl http://127.0.0.1:8001/metrics
```

Gateway-to-Account manual verification, tracing, and degradation example:

```bash
uvicorn account_service.main:app --app-dir services/account-service/src --port 8001
ACCOUNT_SERVICE_URL=http://127.0.0.1:8001 \
  uvicorn event_gateway.main:app --app-dir services/event-gateway/src --port 8000

curl -H "X-Trace-Id: manual-phase5-trace" http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: manual-phase5-trace" \
  -d '{"eventId":"evt-001","accountId":"acct-123","type":"CREDIT","amount":150.00,"currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z","metadata":{"source":"manual"}}'
curl http://127.0.0.1:8000/events/evt-001
curl "http://127.0.0.1:8000/events?account=acct-123"
curl http://127.0.0.1:8001/accounts/acct-123/balance

# Confirm both service logs include the same traceId.

# Stop Account Service, then verify Gateway degrades cleanly.
curl http://127.0.0.1:8000/events/evt-001
curl "http://127.0.0.1:8000/events?account=acct-123"
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{"eventId":"evt-002","accountId":"acct-123","type":"CREDIT","amount":25.00,"currency":"USD","eventTimestamp":"2026-05-15T15:02:11Z","metadata":{"source":"manual-outage"}}'
```

## Implementation Defaults

- **Language/framework**: Python + FastAPI
- **Database**: separate SQLite database per service
- **Service communication**: synchronous REST
- **Trace header**: `X-Trace-Id`
- **Resiliency pattern**: bounded timeout + retry with exponential backoff
- **Metrics**: request counts and Account Service call metrics
