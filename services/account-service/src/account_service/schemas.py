from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TransactionType = Literal["CREDIT", "DEBIT"]


class TransactionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId", min_length=1)
    type: TransactionType
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=1)
    event_timestamp: datetime = Field(alias="eventTimestamp")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("eventTimestamp must include a timezone")
        return value
