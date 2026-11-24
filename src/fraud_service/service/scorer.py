from collections.abc import Sequence
from dataclasses import dataclass

from fraud_service.domain.entities import Decision, FraudScore, RawScore, Transaction
from fraud_service.domain.explanations import Reason, strongest_reasons, typical_variants
from fraud_service.domain.policies import decide
from fraud_service.service.interfaces import Model


@dataclass
class FraudScorer:
    """Use-case: score one transaction, or a batch of them.

    Note what is ABSENT: no FastAPI, no sklearn, no file paths,
    no logging configuration. Pure orchestration = trivially testable.
    """

    model: Model
    block_threshold: float

    def score(self, txn: Transaction) -> FraudScore:
        features = txn.to_features()                 # domain logic
        raw = self.model.predict_proba(features)     # through the protocol
        return self._to_score(txn, raw)

    def score_many(self, txns: Sequence[Transaction]) -> list[FraudScore]:
        """Same features and the same policy as score(), in one model call."""
        if not txns:
            return []
        raws = self.model.predict_proba_many([txn.to_features() for txn in txns])
        return [self._to_score(txn, raw) for txn, raw in zip(txns, raws, strict=True)]

    def explain(self, txn: Transaction, score: FraudScore) -> list[Reason]:
        """The reasons behind an alert, from one batched model call. An allowed transaction
        needs none, and costs no extra call."""
        if score.decision is Decision.ALLOW:
            return []
        variants = typical_variants(txn)
        raws = self.model.predict_proba_many([v.to_features() for v in variants.values()])
        return strongest_reasons(
            score.probability, {field: raw.value for field, raw in zip(variants, raws, strict=True)})

    def _to_score(self, txn: Transaction, raw: RawScore) -> FraudScore:
        return FraudScore(
            transaction_id=txn.transaction_id,
            probability=raw.value,
            decision=decide(raw, self.block_threshold),   # domain policy
            model_version=self.model.model_version,
        )
