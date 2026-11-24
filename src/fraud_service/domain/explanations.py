"""Why a transaction was flagged: which of its inputs pushed its score up.

A reason compares the transaction with a typical one, one input at a time. The same
transaction with only that input made typical is scored again; the drop in the score is that
input's effect. The typical values describe the 5,000 training transactions, and a data check
keeps them in step with data/.

Rules for this file: imports from stdlib + pydantic + the domain ONLY.
"""
from pydantic import BaseModel

from fraud_service.domain.entities import Channel, Transaction

# The typical training transaction: the median amount, the most common channel and category,
# and the median hour in UTC, the clock the model learned its hours on.
TYPICAL_AMOUNT_SAR = 149.24
TYPICAL_CHANNEL = Channel.POS
TYPICAL_CATEGORY = "ELECTRONICS"
TYPICAL_HOUR_UTC = 12

MAX_REASONS = 3        # an analyst reads three reasons; a longer list is noise
MIN_EFFECT = 0.01      # a smaller drop in the score is not a reason

EXPLAINED_FIELDS = ("amount_sar", "channel", "merchant_category", "timestamp")


class Reason(BaseModel):
    field: str         # the request field that pushed the score up
    effect: float      # how much lower the score is when this field takes its typical value


def typical_variants(txn: Transaction) -> dict[str, Transaction]:
    """One variant per explained field: the same transaction with only that field typical.
    Identifiers are never explained: they are not model inputs."""
    return {
        "amount_sar": txn.model_copy(update={"amount_sar": TYPICAL_AMOUNT_SAR}),
        "channel": txn.model_copy(update={"channel": TYPICAL_CHANNEL}),
        "merchant_category": txn.model_copy(update={"merchant_category": TYPICAL_CATEGORY}),
        "timestamp": txn.model_copy(
            update={"timestamp": txn.timestamp.replace(hour=TYPICAL_HOUR_UTC)}),
    }


def strongest_reasons(score: float, typical_scores: dict[str, float]) -> list[Reason]:
    """The fields whose typical value lowers the score the most, strongest first."""
    effects = sorted(((score - typical, field) for field, typical in typical_scores.items()),
                     reverse=True)
    return [Reason(field=field, effect=round(effect, 3))
            for effect, field in effects if effect > MIN_EFFECT][:MAX_REASONS]
