"""Domain entities: the vocabulary of the fraud problem.

Rules for this file:
- imports from stdlib + pydantic ONLY
- no I/O, no framework types, no ML library types
"""
import math
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Channel(StrEnum):
    POS = "pos"
    ECOM = "ecom"
    ATM = "atm"
    TRANSFER = "transfer"


class FeatureVector(BaseModel):
    values: dict[str, float | int | str]


class Transaction(BaseModel):
    """A single card/account transaction to be scored."""

    transaction_id: str = Field(min_length=8)
    amount_sar: float = Field(gt=0, description="Amount in Saudi Riyal")
    channel: Channel
    merchant_category: str
    customer_id: str
    timestamp: datetime

    @field_validator("merchant_category")
    @classmethod
    def normalise_mcc(cls, v: str) -> str:
        # Domain rule: categories are upper-snake, e.g. "GROCERY"
        return v.strip().upper().replace(" ", "_")

    @field_validator("timestamp")
    @classmethod
    def to_utc(cls, v: datetime) -> datetime:
        # The model learned its hours in UTC: every training row is +00:00. One instant must
        # give one hour whatever offset the caller wrote it in, so the domain keeps UTC.
        # A time without an offset is read as UTC (the API refuses those; see schemas.py).
        if v.tzinfo is None or v.utcoffset() is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)

    def to_features(self) -> FeatureVector:
        """The single source of feature logic for serving.

        One place to compare against the training code: the primary
        defence against training/serving skew.
        """
        return FeatureVector(values={
            "amount_log": round(math.log1p(self.amount_sar), 6),
            "channel": self.channel.value,
            "mcc": self.merchant_category,
            "hour_of_day": self.timestamp.hour,
            "is_night": int(self.timestamp.hour < 6),
        })


class RawScore(BaseModel):
    value: float = Field(ge=0.0, le=1.0)


class Decision(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class FraudScore(BaseModel):
    transaction_id: str
    probability: float
    decision: Decision
    model_version: str
