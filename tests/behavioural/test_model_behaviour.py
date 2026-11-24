"""Claims about the MODEL, checked against the real artefact."""
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from fraud_service.config import Settings
from fraud_service.domain.entities import Decision, RawScore, Transaction
from fraud_service.domain.policies import decide

pytestmark = pytest.mark.behavioural

DEFAULT_THRESHOLD = Settings.model_fields["block_threshold"].default   # 0.85, as deployed


def _score(model, txn: Transaction) -> float:
    return model.predict_proba(txn.to_features()).value


def test_invariance_to_merchant_casing(real_model, make_txn):
    """Casing and stray spaces are noise, not signal."""
    a = _score(real_model, make_txn(merchant_category="electronics"))
    b = _score(real_model, make_txn(merchant_category="  ELECTRONICS "))
    assert a == pytest.approx(b, abs=1e-9)


def test_invariance_to_identifiers(real_model, make_txn):
    """Who you are and what the transaction is called must not move the score."""
    a = _score(real_model, make_txn())
    b = _score(real_model, make_txn(transaction_id="TXN-OTHER-9999", customer_id="CUST-1"))
    assert a == pytest.approx(b, abs=1e-9)


@pytest.mark.parametrize("small, large", [(50.0, 50_000.0), (5.0, 500.0), (900.0, 90_000.0)])
def test_directional_amount(real_model, make_txn, small, large):
    """All else equal, a much larger amount must not LOWER fraud probability."""
    assert _score(real_model, make_txn(amount_sar=large)) >= \
        _score(real_model, make_txn(amount_sar=small)) - 1e-6


def test_batch_scoring_equals_one_by_one(real_model, make_txn):
    """The batch fast path must be an optimisation, never a different model."""
    txns = [make_txn(amount_sar=a, channel=c, merchant_category=m)
            for a, c, m in [(12.5, "pos", "grocery"), (49_000.0, "transfer", "jewellery"),
                            (310.0, "ecom", "electronics"), (75.0, "atm", "cash")]]
    batch = [s.value for s in real_model.predict_proba_many([t.to_features() for t in txns])]
    single = [_score(real_model, t) for t in txns]
    assert batch == pytest.approx(single, abs=1e-12)


@pytest.fixture(scope="module")
def labelled_sample(real_model) -> pd.DataFrame:
    """The 5,000 labelled sample transactions, scored by the real artefact in one batch."""
    df = pd.read_csv("data/transactions_sample.csv")
    txns = [Transaction(transaction_id=r.transaction_id, amount_sar=r.amount_sar,
                        channel=r.channel, merchant_category=r.merchant_category,
                        customer_id=r.customer_id, timestamp=r.timestamp)
            for r in df.itertuples()]
    scores = real_model.predict_proba_many([t.to_features() for t in txns])
    return df.assign(score=[s.value for s in scores])


def test_model_ranks_fraud_well_above_a_simple_guess(labelled_sample):
    """Quality floor. The notebook trained on this sample, so this is a tripwire for a model
    that got worse (a wrong artefact, broken features), not a promise about new data."""
    fraud = labelled_sample.is_fraud
    auc = roc_auc_score(fraud, labelled_sample.score)
    amount_only = roc_auc_score(fraud, labelled_sample.amount_sar)   # "bigger is riskier"
    assert auc >= 0.80, f"ranking quality fell to {auc:.3f}"
    assert auc >= amount_only + 0.10, f"barely better than amount alone ({amount_only:.3f})"


def test_default_policy_outcome_on_the_labelled_sample(labelled_sample):
    """What the deployed threshold does with real scores. A block must almost always be
    fraud, and a floor holds on the share of frauds that reach an analyst or a block.
    Raising the threshold lowers that share; this test makes the trade-off visible."""
    decisions = labelled_sample.score.map(lambda p: decide(RawScore(value=p), DEFAULT_THRESHOLD))
    fraud = labelled_sample.is_fraud
    blocked = fraud[decisions == Decision.BLOCK]
    flagged = fraud[decisions != Decision.ALLOW]
    assert len(blocked) > 0, "the default threshold blocks nothing"
    assert blocked.mean() >= 0.90, f"only {blocked.mean():.0%} of blocks are fraud"
    assert flagged.sum() / fraud.sum() >= 0.08, f"only {flagged.sum()} frauds reach an analyst"


@pytest.mark.slow
def test_golden_scores(real_model):
    """The skew tripwire: every reference row must reproduce (within tolerance)."""
    ref = pd.read_csv("data/golden_scores_v3.csv")
    drifted = []
    for row in ref.itertuples():
        txn = Transaction(
            transaction_id=row.transaction_id, amount_sar=row.amount_sar,
            channel=row.channel, merchant_category=row.mcc,
            customer_id=row.customer_id, timestamp=row.timestamp)
        if _score(real_model, txn) != pytest.approx(row.score, abs=1e-6):
            drifted.append(row.transaction_id)
    assert not drifted, f"skew on {len(drifted)} rows, first: {drifted[:5]}"
