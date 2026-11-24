"""Wire contract. These models exist for consumers; keep them stable.
They convert to/from domain entities in routes and never leak inward.

Contract v1.1 (the stricter firewall, see CHANGELOG.md): an amount is a JSON number, never
a string or a boolean, and a timestamp is ISO 8601 text with an explicit UTC offset.
"""
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from fraud_service.domain.entities import Channel, Decision, Transaction


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")   # reject unknown fields loudly

    transaction_id: str = Field(min_length=8, max_length=64, examples=["TXN-2026-00042"])
    # strict: "249.99" and true are refused instead of being coerced to a number
    amount_sar: float = Field(gt=0, le=1_000_000, strict=True, examples=[249.99],
                              description="Transaction amount in SAR, as a JSON number")
    channel: Channel
    merchant_category: str = Field(min_length=2, max_length=40, examples=["electronics"])
    customer_id: str = Field(min_length=4, max_length=64, examples=["CUST-00077"])
    timestamp: AwareDatetime = Field(examples=["2026-07-05T03:30:00+00:00"],
                                     description="ISO 8601 with an explicit UTC offset")

    @field_validator("timestamp", mode="before")
    @classmethod
    def timestamp_must_be_text(cls, v: object) -> object:
        # Lax parsing would turn 1783222200 into a date. A number is ambiguous (seconds or
        # milliseconds?), so the contract asks for ISO 8601 text only. A PydanticCustomError,
        # not a TypeError: pydantic turns it into a 422, a TypeError would become a 500.
        if not isinstance(v, str):
            raise PydanticCustomError("timestamp_type",
                                      "timestamp must be ISO 8601 text with a UTC offset")
        return v

    @field_validator("merchant_category")
    @classmethod
    def category_must_not_be_blank(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("merchant_category must contain at least 2 visible characters")
        return v

    def to_domain(self) -> Transaction:
        return Transaction(**self.model_dump())


class PredictResponse(BaseModel):
    transaction_id: str
    fraud_probability: float = Field(ge=0, le=1)
    decision: Decision
    model_version: str
    trace_id: str


class ErrorDetail(BaseModel):
    field: str         # where the contract was broken, e.g. "amount_sar"
    problem: str       # what was wrong; never the offending value


class ErrorBody(BaseModel):
    code: str          # stable machine-readable contract
    message: str       # human-readable, may change
    trace_id: str
    details: list[ErrorDetail] | None = None     # present on INVALID_REQUEST only


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    git_sha: str
    started_at: datetime


class ReadyResponse(BaseModel):
    status: str
    model_version: str
    checked_at: datetime


# ---- Batch extension: POST /v1/predict:batch -------------------------------------------

MAX_BATCH_ITEMS = 256


class BatchRequest(BaseModel):
    """1 to 256 transactions. Each item is validated on its own, exactly like a
    /v1/predict body, so one bad item cannot sink the other 255."""
    model_config = ConfigDict(extra="forbid")

    items: list[Any] = Field(min_length=1, max_length=MAX_BATCH_ITEMS,
                             description="Each item has the shape of a /v1/predict body")


class BatchItemResult(BaseModel):
    index: int                                  # position in the request: results keep order
    status: Literal["scored", "rejected"]
    transaction_id: str | None = None
    fraud_probability: float | None = Field(default=None, ge=0, le=1)
    decision: Decision | None = None
    details: list[ErrorDetail] | None = None    # why a rejected item was refused


class BatchSummary(BaseModel):
    total: int
    scored: int
    rejected: int


class BatchResponse(BaseModel):
    model_version: str
    trace_id: str
    summary: BatchSummary
    results: list[BatchItemResult]


def problems(errors: Sequence[Any], prefix_parts: int = 0,
             root: str = "item") -> list[ErrorDetail]:
    """Field names and messages from a pydantic error list; never the input values."""
    return [ErrorDetail(field=".".join(str(p) for p in err["loc"][prefix_parts:]) or root,
                        problem=err["msg"]) for err in errors]
