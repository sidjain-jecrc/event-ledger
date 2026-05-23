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

Phase 0 is the project foundation:

- Python + FastAPI service skeletons
- dependency and test configuration
- basic app factories
- placeholder health endpoints
- smoke tests proving both apps can be imported

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

## Implementation Defaults

- **Language/framework**: Python + FastAPI
- **Database**: separate SQLite database per service
- **Service communication**: synchronous REST
- **Trace header**: `X-Trace-Id`
- **Resiliency pattern**: bounded timeout + retry with exponential backoff
- **Metrics**: request counts and Account Service call metrics
