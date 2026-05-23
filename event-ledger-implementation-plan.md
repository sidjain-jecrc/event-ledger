# Event Ledger Implementation Plan

## Summary

This document is the implementation companion to
`event-ledger-candidate-handout.md`.

The handout remains the source of truth for all requirements. Before
implementing any feature, changing behavior, or marking work complete, review
`event-ledger-candidate-handout.md` and confirm the implementation still
satisfies it. If this plan and the handout appear to conflict, resolve the
ambiguity in favor of the handout.

## Phase Progress

- **Phase 0 complete**: project scaffold, dependency/test configuration,
  service app factories, placeholder Gateway health endpoint, Account Service
  health endpoint, and smoke tests.
- **Phase 1 complete**: Account Service SQLite persistence, transaction
  application, `eventId` idempotency, balance/account APIs, health diagnostics,
  request metrics, trace header echoing, structured request logs, tests, and
  README documentation.
- **Phase 2 complete**: Event Gateway SQLite event persistence, payload
  validation, duplicate detection by `eventId`, `GET /events/{eventId}`,
  `GET /events?account=...` ordered by event timestamp, health diagnostics,
  account-applier seam for Phase 3 integration, tests, manual verification, and
  README documentation.
- **Phase 3 complete**: Gateway default account applier now calls Account
  Service over synchronous REST, successful Account application is required
  before Gateway event persistence, duplicate Gateway submissions do not call
  Account Service again, downstream errors are mapped to Gateway HTTP errors,
  integration tests cover Gateway-to-Account balance updates, and README
  documentation includes the two-service verification flow.
- **Phase 4 complete**: Gateway Account Service calls use bounded timeout +
  retry with exponential backoff, retries are limited to transient request
  errors and retryable HTTP statuses, downstream `4xx` errors are not retried,
  exhausted retry attempts return `503 Service Unavailable`, Gateway read
  endpoints keep serving local data during Account Service outage, failed new
  submissions are not stored, tests cover retry/degradation behavior, manual
  outage verification passed, and README documentation explains configuration.

## Architecture Summary

The system has two independently runnable services:

- **Event Gateway API**: public-facing service that receives transaction events,
  validates input, enforces event idempotency, stores event records locally, and
  calls the Account Service over synchronous REST.
- **Account Service**: internal service that owns account state, balances, and
  transaction history.

Each service must use its own embedded or in-memory database. The services must
not share a database, in-process state, or direct storage access. The service
boundary is the REST API contract between the Gateway and Account Service.

## Implementation Plan

1. **Build the Account Service first**
   - Implement `POST /accounts/{accountId}/transactions`.
   - Store transactions with `eventId` as an idempotency key.
   - Ensure duplicate `eventId` submissions do not alter balance twice.
   - Implement balance calculation as `sum(CREDIT) - sum(DEBIT)`.
   - Implement account details and recent transaction retrieval.
   - Add health checks, structured logs, trace ID logging, and custom metrics.

2. **Build the Event Gateway API second**
   - Implement event payload validation.
   - Store accepted event records in the Gateway database.
   - Enforce idempotency by `eventId`.
   - Return the original accepted event for duplicate submissions.
   - List account events ordered by `eventTimestamp`, not arrival time.
   - Call the Account Service to apply each new transaction.

3. **Keep event persistence aligned with account application**
   - Persist Gateway event records only after successful Account Service
     application.
   - This avoids showing unapplied events as accepted.
   - Account Service must still be idempotent by `eventId` to defend against
     Gateway retries and timeout ambiguity.

4. **Add tracing and observability**
   - Generate or accept a trace ID at the Gateway for each incoming request.
   - Propagate the trace ID to Account Service via the `X-Trace-Id` HTTP header.
   - Emit JSON-formatted structured logs from both services.
   - Include timestamp, log level, service name, trace ID, and message in logs.
   - Add health endpoints and at least one custom metric.

5. **Add resiliency**
   - Use bounded timeout + retry with exponential backoff for Gateway calls to
     Account Service.
   - Do not retry indefinitely.
   - Return `503 Service Unavailable` when Account Service cannot be reached or
     does not respond within the configured retry policy.

6. **Add delivery artifacts**
   - Add `docker-compose.yml` to run both services together.
   - Add `README.md` with architecture overview, setup instructions, run
     commands, test commands, and resiliency explanation.

## API Surface

### Event Gateway API

- `POST /events`
  - Submit a transaction event.
  - Validate input.
  - Enforce idempotency by `eventId`.
  - Call Account Service to apply the transaction.

- `GET /events/{id}`
  - Retrieve a single event by its ID from Gateway local storage.

- `GET /events?account={accountId}`
  - List events for an account from Gateway local storage.
  - Results must be ordered by `eventTimestamp`.

- `GET /health`
  - Return Gateway service status and basic diagnostics.

### Account Service

- `POST /accounts/{accountId}/transactions`
  - Apply a transaction to an account.
  - Treat `eventId` as the idempotency key.

- `GET /accounts/{accountId}/balance`
  - Return current account balance.

- `GET /accounts/{accountId}`
  - Return account details and recent transactions.

- `GET /health`
  - Return Account Service status and basic diagnostics.

### Optional But Recommended

- `GET /metrics`
  - Expose custom metrics on one or both services.
  - Useful metrics include request count by endpoint/status, Account Service
    call latency, and Account Service call failures.

## Validation And Failure Rules

- Reject missing required fields with meaningful `4xx` errors.
- Reject non-positive amounts.
- Reject unknown event types.
- Reject invalid timestamps.
- Reject malformed payloads.
- Duplicate `eventId` submissions return the original accepted event and do not
  call Account Service again.
- If Account Service is unavailable, `POST /events` returns
  `503 Service Unavailable` instead of hanging or returning an unhandled `500`.
- Gateway event read endpoints continue working from Gateway local data when
  Account Service is unavailable.
- Balance/account queries should clearly report Account Service unreachability
  when routed through Gateway, or be documented as internal-only if exposed
  directly by Account Service.

## Test Plan

Automated tests must be runnable with a standard command, such as `pytest`.

Required coverage:

- Validation tests for required fields, amount, event type, timestamp, and
  malformed payloads.
- Gateway idempotency tests verifying duplicate `eventId` submissions do not
  create duplicate events or call Account Service again.
- Account Service idempotency tests verifying duplicate transaction application
  does not alter balance twice.
- Out-of-order event tests verifying account event listings are chronological by
  `eventTimestamp`.
- Balance tests verifying CREDIT transactions increase balance and DEBIT
  transactions decrease balance.
- Resiliency tests simulating Account Service failure and timeout behavior.
- Trace propagation tests verifying `X-Trace-Id` flows from Gateway to Account
  Service.
- Integration test covering the full Gateway `POST /events` flow through Account
  Service balance update.
- Health and metrics smoke tests.

## Acceptance Criteria

The implementation is complete when:

- Both services run independently.
- Both services can run together via Docker Compose or clearly documented local
  commands.
- Both services use separate embedded or in-memory databases.
- Gateway event submission validates payloads and applies transactions through
  Account Service.
- Duplicate events are idempotent and do not mutate balances twice.
- Out-of-order events are listed chronologically by `eventTimestamp`.
- Balances are correct regardless of event arrival order.
- Trace IDs are propagated and logged by both services.
- Structured JSON logs are emitted by both services.
- Health endpoints exist on both services.
- At least one custom metric is exposed or logged.
- Gateway handles Account Service unavailability with clear `503` behavior.
- Required automated tests pass with the documented command.
- `README.md` explains architecture, setup, startup, tests, and resiliency
  choice.

## Assumptions

- Default stack: Python + FastAPI unless a later implementation decision changes
  this.
- Default database: SQLite per service, configured independently.
- Default resiliency pattern: timeout + retry with exponential backoff.
- Gateway `ACCOUNT_SERVICE_RETRY_ATTEMPTS` is total attempts, not additional
  retries. Gateway retries request errors/timeouts, `408`, `429`, and `5xx`
  responses. It does not retry Account Service `4xx` responses such as
  `409 Conflict`.
- Default trace header: `X-Trace-Id`.
- Default custom metrics: request count by endpoint/status and Account Service
  call failures/latency.
- Account Service rejects mixed currencies for an existing account with
  `409 Conflict` so balances are not computed across currencies.
- Event Gateway uses the real Gateway-to-Account REST client by default; tests
  can still inject fake account appliers for focused behavior checks.
- This repository starts with `event-ledger-candidate-handout.md`; this document
  is the implementation planning companion.
