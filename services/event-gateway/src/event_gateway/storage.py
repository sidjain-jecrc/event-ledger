from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from event_gateway.schemas import EventRequest


class EventAlreadyExistsError(Exception):
    pass


@dataclass(frozen=True)
class EventRecord:
    event: dict[str, Any]
    created: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sqlite_path(database_url: str) -> str:
    if database_url == "sqlite:///:memory:":
        return ":memory:"
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// database URLs are supported")
    path = database_url.removeprefix("sqlite:///")
    if path != ":memory:":
        parent = Path(path).expanduser().parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_timestamp(value: datetime) -> tuple[str, float]:
    utc_value = value.astimezone(UTC)
    return utc_value.isoformat().replace("+00:00", "Z"), utc_value.timestamp()


def decimal_to_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


class EventRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.database_path = _sqlite_path(database_url)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('CREDIT', 'DEBIT')),
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    event_timestamp TEXT NOT NULL,
                    event_timestamp_epoch REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_account_timestamp
                    ON events(account_id, event_timestamp_epoch ASC, event_id ASC);
                """
            )

    def check_connectivity(self) -> bool:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def create_event(self, event: EventRequest) -> EventRecord:
        existing = self.get_event(event.event_id)
        if existing is not None:
            return EventRecord(event=existing, created=False)

        timestamp, epoch = _normalize_timestamp(event.event_timestamp)
        with self.connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO events (
                        event_id,
                        account_id,
                        type,
                        amount,
                        currency,
                        event_timestamp,
                        event_timestamp_epoch,
                        metadata_json,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.account_id,
                        event.type,
                        str(event.amount),
                        event.currency,
                        timestamp,
                        epoch,
                        json.dumps(event.metadata, sort_keys=True),
                        "ACCEPTED",
                        _utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise EventAlreadyExistsError(event.event_id) from exc

        stored_event = self.get_event(event.event_id)
        if stored_event is None:
            raise RuntimeError(f"Event {event.event_id} was not stored")
        return EventRecord(event=stored_event, created=True)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return self._event_from_row(row)

    def list_events_for_account(self, account_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM events
                WHERE account_id = ?
                ORDER BY event_timestamp_epoch ASC, event_id ASC
                """,
                (account_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eventId": row["event_id"],
            "accountId": row["account_id"],
            "type": row["type"],
            "amount": decimal_to_json_number(Decimal(row["amount"])),
            "currency": row["currency"],
            "eventTimestamp": row["event_timestamp"],
            "metadata": json.loads(row["metadata_json"]),
            "status": row["status"],
        }
