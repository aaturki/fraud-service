import math

import pytest

from fraud_service.domain.entities import Decision, RawScore
from fraud_service.service.scorer import FraudScorer
from tests.conftest import ConstantModel


class AmountModel(ConstantModel):
    """Scores 0.95 above 1,000 SAR and 0.20 below, and counts its batched calls."""
    calls = 0

    def predict_proba(self, features):
        return RawScore(value=0.95 if features.values["amount_log"] > math.log1p(1_000) else 0.20)

    def predict_proba_many(self, features):
        self.calls += 1
        return [self.predict_proba(f) for f in features]


@pytest.mark.unit
@pytest.mark.parametrize(("p", "expected"), [
    (0.99, Decision.BLOCK), (0.75, Decision.REVIEW), (0.10, Decision.ALLOW)])
def test_scorer_applies_policy_and_carries_version(sample_txn, p, expected):
    scorer = FraudScorer(model=ConstantModel(p, version="test-9"), block_threshold=0.85)
    result = scorer.score(sample_txn)
    assert result.decision is expected
    assert result.probability == p
    assert result.model_version == "test-9"
    assert result.transaction_id == sample_txn.transaction_id


@pytest.mark.unit
def test_score_many_matches_score_item_by_item(make_txn):
    scorer = FraudScorer(model=ConstantModel(0.75), block_threshold=0.85)
    txns = [make_txn(transaction_id=f"TXN-MANY-{i:04d}") for i in range(4)]
    assert scorer.score_many(txns) == [scorer.score(txn) for txn in txns]


@pytest.mark.unit
def test_score_many_of_nothing_calls_no_model():
    class Exploding(ConstantModel):
        def predict_proba_many(self, features):
            raise AssertionError("the model must not be called for an empty batch")

    assert FraudScorer(model=Exploding(0.5), block_threshold=0.85).score_many([]) == []


@pytest.mark.unit
def test_an_alert_names_the_input_that_drove_it(make_txn):
    """Only the amount moves this model, so the amount is the only reason."""
    model = AmountModel(0.0)
    scorer = FraudScorer(model=model, block_threshold=0.85)
    txn = make_txn(amount_sar=5_000.0)
    score = scorer.score(txn)
    assert score.decision is Decision.BLOCK
    assert [(r.field, r.effect) for r in scorer.explain(txn, score)] == [("amount_sar", 0.75)]
    assert model.calls == 1                          # four variants, one batched call


@pytest.mark.unit
def test_an_allowed_transaction_gets_no_reasons_and_no_extra_call(make_txn):
    model = AmountModel(0.0)
    scorer = FraudScorer(model=model, block_threshold=0.85)
    txn = make_txn(amount_sar=50.0)
    score = scorer.score(txn)
    assert score.decision is Decision.ALLOW
    assert scorer.explain(txn, score) == []
    assert model.calls == 0
