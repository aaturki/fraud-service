"""The reason rule: which inputs pushed a score up, compared with a typical transaction."""
import pytest

from fraud_service.domain.explanations import (
    EXPLAINED_FIELDS,
    MAX_REASONS,
    TYPICAL_AMOUNT_SAR,
    TYPICAL_CATEGORY,
    TYPICAL_CHANNEL,
    TYPICAL_HOUR_UTC,
    strongest_reasons,
    typical_variants,
)

pytestmark = pytest.mark.unit


def test_each_variant_changes_exactly_one_explained_field(make_txn):
    txn = make_txn(amount_sar=5_000.0, channel="transfer", merchant_category="jewelry")
    variants = typical_variants(txn)
    assert tuple(variants) == EXPLAINED_FIELDS
    original = txn.model_dump()
    for field, variant in variants.items():
        changed = {k for k, v in variant.model_dump().items() if v != original[k]}
        assert changed == {field}, f"the {field} variant changed {changed}"


def test_variants_take_the_typical_values(make_txn):
    variants = typical_variants(make_txn())
    assert variants["amount_sar"].amount_sar == TYPICAL_AMOUNT_SAR
    assert variants["channel"].channel == TYPICAL_CHANNEL
    assert variants["merchant_category"].merchant_category == TYPICAL_CATEGORY
    assert variants["timestamp"].timestamp.hour == TYPICAL_HOUR_UTC


def test_reasons_are_strongest_first_capped_and_above_the_floor():
    reasons = strongest_reasons(0.90, {"amount_sar": 0.30, "channel": 0.85,
                                       "merchant_category": 0.895, "timestamp": 0.60})
    assert [(r.field, r.effect) for r in reasons] == [
        ("amount_sar", 0.6), ("timestamp", 0.3), ("channel", 0.05)]
    assert len(reasons) <= MAX_REASONS


def test_an_input_that_lowers_nothing_is_not_a_reason():
    assert strongest_reasons(0.50, {"amount_sar": 0.50, "channel": 0.70}) == []
