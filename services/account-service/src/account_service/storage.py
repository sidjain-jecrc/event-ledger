from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from account_service.schemas import TransactionRequest


class AccountNotFoundError(Exception):
    pass


class CurrencyMismatchError(Exception):
    pass


@dataclass(frozen=True)
class AppliedTransaction:
    transaction: dict[str, Any]
    balance: Decimal
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


class AccountRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.database_path = _sqlite_path(database_url)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    currency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    event_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('CREDIT', 'DEBIT')),
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    event_timestamp TEXT NOT NULL,
                    event_timestamp_epoch REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_account_recent
                    ON transactions(account_id, event_timestamp_epoch DESC);
                """
            )

    def check_connectivity(self) -> bool:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def apply_transaction(
        self,
        account_id: str,
        request: TransactionRequest,
    ) -> AppliedTransaction:
        timestamp, epoch = _normalize_timestamp(request.event_timestamp)
        now = _utc_now()
        metadata_json = json.dumps(request.metadata, sort_keys=True)

        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM transactions WHERE event_id = ?",
                (request.event_id,),
            ).fetchone()
            if existing is not None:
                return AppliedTransaction(
                    transaction=self._transaction_from_row(existing),
                    balance=self._balance_for_account(connection, existing["account_id"]),
                    created=False,
                )

            account = connection.execute(
                "SELECT * FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is not None and account["currency"] != request.currency:
                raise CurrencyMismatchError(
                    f"Account {account_id} already uses {account['currency']}"
                )

            if account is None:
                connection.execute(
                    """
                    INSERT INTO accounts (account_id, currency, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (account_id, request.currency, now, now),
                )
            else:
                connection.execute(
                    "UPDATE accounts SET updated_at = ? WHERE account_id = ?",
                    (now, account_id),
                )

            connection.execute(
                """
                INSERT INTO transactions (
                    event_id,
                    account_id,
                    type,
                    amount,
                    currency,
                    event_timestamp,
                    event_timestamp_epoch,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.event_id,
                    account_id,
                    request.type,
                    str(request.amount),
                    request.currency,
                    timestamp,
                    epoch,
                    metadata_json,
                    now,
                ),
            )

            row = connection.execute(
                "SELECT * FROM transactions WHERE event_id = ?",
                (request.event_id,),
            ).fetchone()
            return AppliedTransaction(
                transaction=self._transaction_from_row(row),
                balance=self._balance_for_account(connection, account_id),
                created=True,
            )

    def get_balance(self, account_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            account = self._account_row(connection, account_id)
            balance = self._balance_for_account(connection, account_id)
            return {
                "accountId": account_id,
                "balance": decimal_to_json_number(balance),
                "currency": account["currency"],
            }

    def get_account(self, account_id: str, recent_limit: int = 10) -> dict[str, Any]:
        with self.connect() as connection:
            account = self._account_row(connection, account_id)
            balance = self._balance_for_account(connection, account_id)
            transaction_count = connection.execute(
                "SELECT COUNT(*) AS count FROM transactions WHERE account_id = ?",
                (account_id,),
            ).fetchone()["count"]
            recent_transactions = [
                self._transaction_from_row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM transactions
                    WHERE account_id = ?
                    ORDER BY event_timestamp_epoch DESC, event_id ASC
                    LIMIT ?
                    """,
                    (account_id, recent_limit),
                ).fetchall()
            ]
            return {
                "accountId": account_id,
                "currency": account["currency"],
                "balance": decimal_to_json_number(balance),
                "transactionCount": transaction_count,
                "recentTransactions": recent_transactions,
            }

    def _account_row(
        self,
        connection: sqlite3.Connection,
        account_id: str,
    ) -> sqlite3.Row:
        account = connection.execute(
            "SELECT * FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if account is None:
            raise AccountNotFoundError(f"Account {account_id} was not found")
        return account

    def _balance_for_account(
        self,
        connection: sqlite3.Connection,
        account_id: str,
    ) -> Decimal:
        rows = connection.execute(
            "SELECT type, amount FROM transactions WHERE account_id = ?",
            (account_id,),
        ).fetchall()

        balance = Decimal("0")
        for row in rows:
            amount = Decimal(row["amount"])
            if row["type"] == "CREDIT":
                balance += amount
            else:
                balance -= amount
        return balance

    def _transaction_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eventId": row["event_id"],
            "accountId": row["account_id"],
            "type": row["type"],
            "amount": decimal_to_json_number(Decimal(row["amount"])),
            "currency": row["currency"],
            "eventTimestamp": row["event_timestamp"],
            "metadata": json.loads(row["metadata_json"]),
        }
