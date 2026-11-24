from collections.abc import Sequence
from typing import Protocol

from fraud_service.domain.entities import FeatureVector, RawScore


class Model(Protocol):
    """Anything that can score a feature vector.

    Implementations: SklearnModel (prod), ConstantModel (tests),
    RemoteModel (future: calls a model server).
    The service layer knows ONLY this signature.
    """

    model_version: str

    def predict_proba(self, features: FeatureVector) -> RawScore: ...

    def predict_proba_many(self, features: Sequence[FeatureVector]) -> list[RawScore]:
        """One call for many rows, in input order: the batch endpoint's fast path."""
        ...
