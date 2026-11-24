"""Reasons behind an alert, through the API: field names and effects, never values."""
import json
import math
import pathlib

import pytest
from fastapi.testclient import TestClient

from fraud_service.api.app import create_app
from fraud_service.api.routes import get_scorer
from fraud_service.domain.entities import FeatureVector, RawScore
from fraud_service.domain.explanations import EXPLAINED_FIELDS
from fraud_service.service.scorer import FraudScorer

SAMPLE = json.loads(pathlib.Path("payloads/sample.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.integration


class AmountAndNightModel:
    """A large amount adds 0.55 and night adds 0.10 to a base of 0.30: two possible reasons."""
    model_version = "reasons-test"

    def predict_proba(self, features: FeatureVector) -> RawScore:
        v = features.values
        large = float(v["amount_log"]) > math.log1p(1_000)
        return RawScore(value=0.30 + 0.55 * large + 0.10 * int(v["is_night"]))

    def predict_proba_many(self, features: list[FeatureVector]) -> list[RawScore]:
        return [self.predict_proba(f) for f in features]


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    scorer = FraudScorer(model=AmountAndNightModel(), block_threshold=0.85)
    app.dependency_overrides[get_scorer] = lambda: scorer
    return TestClient(app)


def test_an_alert_lists_its_reasons_strongest_first(client):
    # 5,000 SAR at 03:30 UTC scores 0.95, a block: the amount explains 0.55, the hour 0.10
    body = client.post("/v1/predict", json={**SAMPLE, "amount_sar": 5_000.0}).json()
    assert body["decision"] == "block"
    assert body["reasons"] == [{"field": "amount_sar", "effect": 0.55},
                               {"field": "timestamp", "effect": 0.1}]


def test_reasons_name_fields_never_values(client):
    body = client.post("/v1/predict", json={**SAMPLE, "amount_sar": 5_000.0}).json()
    assert {r["field"] for r in body["reasons"]} <= set(EXPLAINED_FIELDS)
    text = json.dumps(body["reasons"])
    assert SAMPLE["customer_id"] not in text
    assert "5000" not in text


def test_an_allowed_transaction_has_no_reasons(client):
    body = client.post("/v1/predict", json={**SAMPLE, "amount_sar": 20.0}).json()
    assert body["decision"] == "allow"                  # 0.30 + 0.10 at night = 0.40
    assert body["reasons"] == []


def test_openapi_documents_reasons(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["PredictResponse"]
    assert "reasons" in schema["properties"]
