"""Contract v1.1, the stricter firewall: what the wire schema accepts and refuses."""
import json
import pathlib

import pytest
from pydantic import ValidationError

from fraud_service.api.schemas import PredictRequest

SAMPLE = json.loads(pathlib.Path("payloads/sample.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.unit


def _errors(**patch: object) -> list[dict]:
    with pytest.raises(ValidationError) as caught:
        PredictRequest.model_validate({**SAMPLE, **patch})
    return caught.value.errors()


def test_sample_payload_is_valid():
    assert PredictRequest.model_validate(SAMPLE).amount_sar == pytest.approx(249.99)


def test_integer_amount_is_still_a_number():
    assert PredictRequest.model_validate({**SAMPLE, "amount_sar": 250}).amount_sar == 250


@pytest.mark.parametrize("amount", ["249.99", "250", True, False])
def test_amount_must_be_a_json_number(amount):
    assert _errors(amount_sar=amount)[0]["loc"] == ("amount_sar",)


@pytest.mark.parametrize("timestamp", ["2026-07-05T03:30:00", "2026-07-05", 1783222200, 1.5])
def test_timestamp_must_be_iso_text_with_an_offset(timestamp):
    assert _errors(timestamp=timestamp)[0]["loc"] == ("timestamp",)


@pytest.mark.parametrize("timestamp", ["2026-07-05T03:30:00Z", "2026-07-05T06:30:00+03:00"])
def test_any_explicit_offset_is_accepted(timestamp):
    assert PredictRequest.model_validate({**SAMPLE, "timestamp": timestamp}).timestamp.utcoffset() \
        is not None


def test_same_instant_in_riyadh_and_utc_is_the_same_transaction():
    utc = PredictRequest.model_validate({**SAMPLE, "timestamp": "2026-07-05T00:30:00+00:00"})
    riyadh = PredictRequest.model_validate({**SAMPLE, "timestamp": "2026-07-05T03:30:00+03:00"})
    assert utc.timestamp == riyadh.timestamp


@pytest.mark.parametrize("category", ["  ", "   x ", "\t\t"])
def test_blank_merchant_category_is_refused(category):
    assert _errors(merchant_category=category)[0]["loc"] == ("merchant_category",)


def test_error_messages_never_carry_the_value():
    problems = " ".join(str(e["msg"]) for e in _errors(amount_sar="987654.32"))
    assert "987654" not in problems
