import pytest

from fraud_service.domain.entities import Decision
from fraud_service.service.scorer import FraudScorer
from tests.conftest import ConstantModel


@pytest.mark.unit
@pytest.mark.parametrize("p, expected", [
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
