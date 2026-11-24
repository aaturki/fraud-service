"""The ONLY file in the service that imports sklearn/joblib/pandas.

If we move to ONNX or a remote model server, we add a sibling
adapter and change one line in the composition root.
"""
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from fraud_service.domain.entities import FeatureVector, RawScore


class SklearnModel:
    def __init__(self, pipeline: Any, model_version: str) -> None:
        self._pipeline = pipeline          # full sklearn Pipeline: encoder + model
        self.model_version = model_version

    @classmethod
    def load(cls, path: Path) -> "SklearnModel":
        """Explicit, failable loading: called by an entrypoint at startup,
        NEVER at import time. The version travels with the artefact."""
        bundle = joblib.load(path)         # {"pipeline": ..., "version": "v3.2.0"}
        return cls(bundle["pipeline"], bundle["version"])

    def predict_proba(self, features: FeatureVector) -> RawScore:
        frame = pd.DataFrame([features.values])
        proba = float(self._pipeline.predict_proba(frame)[0, 1])
        return RawScore(value=proba)

    def predict_proba_many(self, features: Sequence[FeatureVector]) -> list[RawScore]:
        # One DataFrame, one pipeline call: the per-call overhead is paid once per batch.
        frame = pd.DataFrame([f.values for f in features])
        return [RawScore(value=float(p)) for p in self._pipeline.predict_proba(frame)[:, 1]]
