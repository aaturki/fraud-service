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

pytestmark = pytest.mark.data

SAMPLE_PATH = "data/transactions_sample.csv"
ROWS = 5_000
SAMPLE_COLUMNS = ["transaction_id", "amount_sar", "channel", "merchant_category",
                  "customer_id", "timestamp", "is_fraud"]


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_PATH)


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
