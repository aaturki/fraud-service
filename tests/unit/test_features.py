from datetime import UTC, datetime

import pytest


@pytest.mark.unit
def test_feature_names_are_stable(sample_txn):
    """Feature-name drift IS training/serving skew. Freeze the contract."""
    assert set(sample_txn.to_features().values) == {
        "amount_log", "channel", "mcc", "hour_of_day", "is_night"}


@pytest.mark.unit
@pytest.mark.parametrize(("hour", "expected"), [(0, 1), (5, 1), (6, 0), (15, 0), (23, 0)])
def test_night_flag_boundaries(make_txn, sample_txn, hour, expected):
    txn = make_txn(timestamp=sample_txn.timestamp.replace(hour=hour))
    assert txn.to_features().values["is_night"] == expected


@pytest.mark.unit
def test_mcc_normalised_from_messy_input(make_txn):
    txn = make_txn(merchant_category="  home appliances ")
    assert txn.to_features().values["mcc"] == "HOME_APPLIANCES"


@pytest.mark.unit
@pytest.mark.parametrize("written_as", [
    "2026-07-05T00:30:00+00:00",     # UTC
    "2026-07-05T03:30:00+03:00",     # Riyadh
    "2026-07-04T19:30:00-05:00",     # New York, the evening before
    "2026-07-05T06:00:00+05:30",     # New Delhi
])
def test_one_instant_gives_one_hour_whatever_the_offset(make_txn, written_as):
    """The model learned UTC hours: 00:30 UTC is hour 0 and night, however it is written."""
    features = make_txn(timestamp=written_as).to_features().values
    assert (features["hour_of_day"], features["is_night"]) == (0, 1)


@pytest.mark.unit
def test_a_time_without_an_offset_is_read_as_utc(make_txn):
    """The API refuses a time without an offset (contract 1.1). The domain still accepts
    one and reads it on the training clock, UTC."""
    txn = make_txn(timestamp=datetime(2026, 7, 5, 0, 30))
    assert txn.timestamp == datetime(2026, 7, 5, 0, 30, tzinfo=UTC)
