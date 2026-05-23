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

Phase 2 is the Event Gateway local ledger core:

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
- Event Gateway no-op account applier seam for Phase 3 REST integration

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

Phase 2 implements Gateway-local behavior. The Gateway uses a no-op account
applier for now; Phase 3 will replace this seam with the real synchronous REST
call to Account Service.

### `POST /events`

Validates and accepts a transaction event into Gateway local storage. New events
return `201 Created`. Duplicate `eventId` submissions return the original stored
event with `200 OK` and do not re-apply the account step.

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

## Phase 2 Verification

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

Gateway manual verification example:

```bash
uvicorn event_gateway.main:app --app-dir services/event-gateway/src --port 8000
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{"eventId":"evt-001","accountId":"acct-123","type":"CREDIT","amount":150.00,"currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z","metadata":{"source":"manual"}}'
curl http://127.0.0.1:8000/events/evt-001
curl "http://127.0.0.1:8000/events?account=acct-123"
```

## Implementation Defaults

- **Language/framework**: Python + FastAPI
- **Database**: separate SQLite database per service
- **Service communication**: synchronous REST
- **Trace header**: `X-Trace-Id`
- **Resiliency pattern**: bounded timeout + retry with exponential backoff
- **Metrics**: request counts and Account Service call metrics
