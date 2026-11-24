"""Data checks: the files the model and the golden test rely on are what we expect.

These tests only read data/; they never write to it. When one fails, the data changed, not
the code: find out who changed it and why before touching anything else.
"""
from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from fraud_service.api.schemas import PredictRequest
from fraud_service.domain.entities import Channel
from fraud_service.domain.explanations import (
    TYPICAL_AMOUNT_SAR,
    TYPICAL_CATEGORY,
    TYPICAL_CHANNEL,
    TYPICAL_HOUR_UTC,
)

pytestmark = pytest.mark.data

SAMPLE_PATH = "data/transactions_sample.csv"
GOLDEN_PATH = "data/golden_scores_v3.csv"
ROWS = 5_000
SAMPLE_COLUMNS = ["transaction_id", "amount_sar", "channel", "merchant_category",
                  "customer_id", "timestamp", "is_fraud"]
GOLDEN_COLUMNS = ["transaction_id", "amount_sar", "channel", "mcc", "customer_id",
                  "timestamp", "score"]


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_PATH)


@pytest.fixture(scope="module")
def golden() -> pd.DataFrame:
    return pd.read_csv(GOLDEN_PATH)


def test_sample_has_the_expected_columns_and_no_gaps(sample):
    assert list(sample.columns) == SAMPLE_COLUMNS
    assert len(sample) == ROWS
    assert not sample.isna().any().any(), "a missing value would be scored as something else"


def test_sample_identifiers_are_unique_and_well_formed(sample):
    assert sample.transaction_id.is_unique, "two rows with one id would be reported as one"
    assert sample.transaction_id.str.fullmatch(r"TXN-\d{4}-\d{5}").all()
    assert sample.customer_id.str.fullmatch(r"CUST-\d{5}").all()


def test_sample_labels_and_channels_make_sense(sample):
    assert sample.is_fraud.isin([0, 1]).all()
    assert 0 < sample.is_fraud.mean() < 0.5, "fraud must be present, and the minority class"
    assert set(sample.channel) == {c.value for c in Channel}, "every channel, and only those"


def test_sample_times_carry_utc_and_none_is_in_the_future(sample):
    assert sample.timestamp.str.endswith("+00:00").all(), "every time states its UTC offset"
    times = pd.to_datetime(sample.timestamp, format="ISO8601")
    assert times.max() <= pd.Timestamp(datetime.now(UTC)), "no transaction from the future"


def test_every_sample_row_passes_the_api_firewall(sample):
    """The reference data must be valid input for our own contract (v1.1)."""
    rejected = []
    for row in sample.drop(columns="is_fraud").to_dict("records"):
        try:
            PredictRequest.model_validate(row)
        except ValidationError:
            rejected.append(row["transaction_id"])
    assert not rejected, f"{len(rejected)} rows rejected, first: {rejected[:5]}"


def test_typical_values_for_reasons_describe_the_sample(sample):
    """Reasons compare a transaction with a typical one: it must be typical of this sample."""
    hours = pd.to_datetime(sample.timestamp, format="ISO8601").dt.hour
    assert round(float(sample.amount_sar.median()), 2) == TYPICAL_AMOUNT_SAR
    assert sample.channel.mode()[0] == TYPICAL_CHANNEL.value
    assert sample.merchant_category.mode()[0] == TYPICAL_CATEGORY
    assert int(hours.median()) == TYPICAL_HOUR_UTC


def test_golden_file_has_the_expected_columns_and_no_gaps(golden):
    assert list(golden.columns) == GOLDEN_COLUMNS
    assert len(golden) == ROWS
    assert not golden.isna().any().any()


def test_golden_scores_are_probabilities_with_a_real_spread(golden):
    assert golden.score.between(0, 1).all()
    assert golden.score.std() > 0.05, "near-constant scores mean a broken model wrote the file"


def test_golden_file_records_exactly_the_sample(sample, golden):
    """The golden file is the model's answers for the sample's transactions, row for row.
    Then the golden tripwire and the quality floor check the same data, and a change to one
    file alone is caught here."""
    same_column = {"transaction_id": "transaction_id", "amount_sar": "amount_sar",
                   "channel": "channel", "merchant_category": "mcc",
                   "customer_id": "customer_id", "timestamp": "timestamp"}
    for in_sample, in_golden in same_column.items():
        assert sample[in_sample].equals(golden[in_golden]), f"{in_sample} differs from {in_golden}"
