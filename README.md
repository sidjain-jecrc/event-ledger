# Event Ledger

Event Ledger is a two-service system for processing financial transaction
events. The source requirements live in `event-ledger-candidate-handout.md`.

## Architecture

- **Event Gateway API** is the public-facing service. It validates submitted
  events, enforces idempotency by `eventId`, stores accepted event records in
  its own SQLite database, and calls Account Service over synchronous REST.
- **Account Service** is the internal account-state service. It stores
  transactions in its own SQLite database, applies idempotency by `eventId`, and
  computes account balances as CREDIT minus DEBIT.

The services run as independent processes. They do not share a database or
in-process state. Docker Compose starts both services and wires Gateway to
Account Service through `http://account-service:8001`.

## Prerequisites

- Docker Desktop or another Docker Compose compatible runtime.
- `curl` for endpoint verification.
- Python 3.11+ and `pip` only if you want to run the automated tests locally.

## Start And Stop Services

Start both services with Docker Compose:

```bash
docker compose up --build
```

Service URLs:

- Event Gateway API: `http://127.0.0.1:8000`
- Account Service: `http://127.0.0.1:8001`

Quick smoke check:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

Stop services and keep Docker volumes:

```bash
docker compose down
```

Stop services and remove persisted SQLite volumes:

```bash
docker compose down -v
```

Validate the Compose file without starting services:

```bash
docker compose config
```

## Run Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

## Resiliency Pattern

The Gateway uses **timeout + retry with exponential backoff** for its
synchronous REST call to Account Service.

This was selected because it handles transient network failures, short Account
Service restarts, and slow responses without letting Gateway requests hang
indefinitely. Retries are safe because both services use `eventId` as an
idempotency key, so a retried transaction cannot be applied twice. If all
attempts fail, Gateway returns `503 Service Unavailable` and does not store the
event as accepted.

Configuration:

- `ACCOUNT_SERVICE_TIMEOUT_SECONDS`: per-attempt timeout, default `2.0`.
- `ACCOUNT_SERVICE_RETRY_ATTEMPTS`: total attempts, default `3`.
- `ACCOUNT_SERVICE_RETRY_BACKOFF_SECONDS`: initial retry backoff, default `0.1`.

## Endpoint Behavior Checklist

Set shell variables used by the examples:

```bash
GATEWAY=http://127.0.0.1:8000
ACCOUNT=http://127.0.0.1:8001
TRACE=readme-trace-001
```

### 1. Health Checks

Expected behavior:

- Gateway `/health` returns service status, database diagnostics, and Account
  Service URL.
- Account Service `/health` returns service status and database diagnostics.
- Gateway returns the same `X-Trace-Id` when one is provided.

```bash
curl -i -H "X-Trace-Id: $TRACE" "$GATEWAY/health"
curl -i -H "X-Trace-Id: $TRACE" "$ACCOUNT/health"
```

### 2. Submit An Event Through Gateway

Expected behavior:

- Gateway validates the event.
- Gateway calls Account Service before storing the event.
- New event returns `201 Created`.
- Response includes `status: "ACCEPTED"`.
- Response includes `X-Trace-Id`.

```bash
curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-readme-001",
    "accountId": "acct-readme",
    "type": "CREDIT",
    "amount": 150.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
    "metadata": {
      "source": "readme"
    }
  }'
```

### 3. Gateway Event Idempotency

Expected behavior:

- Reusing `eventId` returns the originally accepted event with `200 OK`.
- Gateway does not call Account Service again.
- Account balance is not changed by the duplicate.

```bash
curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-readme-001",
    "accountId": "acct-readme",
    "type": "DEBIT",
    "amount": 999.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T18:02:11Z",
    "metadata": {
      "source": "readme-duplicate"
    }
  }'
```

### 4. Read One Gateway Event

Expected behavior:

- Existing event returns `200 OK`.
- Missing event returns `404 Not Found`.

```bash
curl -i "$GATEWAY/events/evt-readme-001"
curl -i "$GATEWAY/events/missing-event"
```

### 5. Out-Of-Order Event Listing

Expected behavior:

- Events may arrive out of order.
- Gateway lists account events chronologically by `eventTimestamp`.
- After these commands, expected order for `acct-readme` is:
  `evt-readme-002`, `evt-readme-001`, `evt-readme-003`.

```bash
curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-readme-003",
    "accountId": "acct-readme",
    "type": "DEBIT",
    "amount": 25.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T16:02:11Z",
    "metadata": {
      "source": "readme"
    }
  }'

curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-readme-002",
    "accountId": "acct-readme",
    "type": "CREDIT",
    "amount": 10.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T13:02:11Z",
    "metadata": {
      "source": "readme"
    }
  }'

curl -i "$GATEWAY/events?account=acct-readme"
```

### 6. Gateway Validation Errors

Expected behavior:

- Invalid events return a meaningful `4xx` response.
- Non-positive amounts are rejected.
- Unknown event types are rejected.

```bash
curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "evt-readme-invalid",
    "accountId": "acct-readme",
    "type": "TRANSFER",
    "amount": 0,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z"
  }'
```

### 7. Account Balance

Expected behavior:

- Balance is CREDIT minus DEBIT.
- For the `acct-readme` events above, expected balance is `135`.

```bash
curl -i "$ACCOUNT/accounts/acct-readme/balance"
```

### 8. Account Details

Expected behavior:

- Account details include account ID, currency, current balance, transaction
  count, and recent transactions.
- Recent transactions are returned newest first.

```bash
curl -i "$ACCOUNT/accounts/acct-readme"
```

### 9. Account Service Direct Transaction And Idempotency

Expected behavior:

- Account Service accepts direct internal transaction application.
- New transaction returns `201 Created`.
- Duplicate `eventId` returns `200 OK` with `idempotent: true`.
- Duplicate transaction does not change balance twice.

```bash
curl -i -X POST "$ACCOUNT/accounts/acct-direct/transactions" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-direct-001",
    "type": "CREDIT",
    "amount": 50.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
    "metadata": {
      "source": "readme-direct"
    }
  }'

curl -i -X POST "$ACCOUNT/accounts/acct-direct/transactions" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $TRACE" \
  -d '{
    "eventId": "evt-direct-001",
    "type": "CREDIT",
    "amount": 50.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
    "metadata": {
      "source": "readme-direct"
    }
  }'

curl -i "$ACCOUNT/accounts/acct-direct/balance"
```

### 10. Account Service Validation

Expected behavior:

- Invalid internal transaction payloads return a meaningful `4xx` response.

```bash
curl -i -X POST "$ACCOUNT/accounts/acct-direct/transactions" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "evt-direct-invalid",
    "type": "TRANSFER",
    "amount": 0,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z"
  }'
```

### 11. Metrics

Expected behavior:

- Gateway `/metrics` includes request counts, Account Service call outcomes,
  and Account Service call latency aggregates.
- Account Service `/metrics` includes request counts.

```bash
curl -i "$GATEWAY/metrics"
curl -i "$ACCOUNT/metrics"
```

### 12. Trace Propagation

Expected behavior:

- Gateway logs include the client-provided trace ID.
- Account Service logs include the same trace ID for the downstream transaction
  request.

```bash
docker compose logs event-gateway account-service | grep "$TRACE"
```

### 13. Graceful Degradation

Expected behavior:

- When Account Service is stopped, Gateway `POST /events` returns
  `503 Service Unavailable`.
- Gateway read endpoints still work because they use Gateway local storage.
- Failed new events are not stored.

```bash
docker compose stop account-service

curl -i "$GATEWAY/events/evt-readme-001"
curl -i "$GATEWAY/events?account=acct-readme"

curl -i -X POST "$GATEWAY/events" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "evt-readme-down",
    "accountId": "acct-readme",
    "type": "CREDIT",
    "amount": 25.00,
    "currency": "USD",
    "eventTimestamp": "2026-05-15T17:02:11Z",
    "metadata": {
      "source": "readme-outage"
    }
  }'

curl -i "$GATEWAY/events/evt-readme-down"

docker compose start account-service
```

## Final Acceptance Checklist

- Docker Compose starts and stops both services.
- Each service uses a separate SQLite database and Docker volume.
- Gateway validates events and rejects malformed payloads.
- Gateway stores events only after Account Service accepts the transaction.
- Gateway duplicate `eventId` submissions are idempotent.
- Gateway event listings are ordered by `eventTimestamp`.
- Account Service computes balances as CREDIT minus DEBIT.
- Account Service duplicate `eventId` transactions are idempotent.
- Gateway returns `503 Service Unavailable` when Account Service is unreachable.
- Gateway read endpoints continue working during Account Service outage.
- Gateway propagates `X-Trace-Id` to Account Service.
- Both services emit JSON request logs containing `traceId`.
- Both services expose `/health`.
- Both services expose `/metrics`.
- Automated tests pass with `pytest`.
