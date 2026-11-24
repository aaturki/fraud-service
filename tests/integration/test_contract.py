"""The HTTP contract beyond the happy path: headers, error codes, limits, documentation."""
import json
import pathlib
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fraud_service.api.app import MAX_BODY_BYTES, create_app
from fraud_service.domain.entities import FeatureVector, RawScore
from fraud_service.service.scorer import FraudScorer

SAMPLE = json.loads(pathlib.Path("payloads/sample.json").read_text(encoding="utf-8"))
GENERATED_TRACE = re.compile(r"[0-9a-f]{16}")

pytestmark = pytest.mark.integration


class FixedModel:
    def __init__(self, p: float, version: str) -> None:
        self._p, self.model_version = p, version

    def predict_proba(self, features: FeatureVector) -> RawScore:
        return RawScore(value=self._p)

    def predict_proba_many(self, features: list[FeatureVector]) -> list[RawScore]:
        return [RawScore(value=self._p) for _ in features]


@pytest.fixture
def ready_client() -> TestClient:
    """The state a container is in once start-up has finished, without the real artefact."""
    app = create_app()
    app.state.scorer = FraudScorer(model=FixedModel(0.10, "test-9"), block_threshold=0.85)
    app.state.model_version = "test-9"
    app.state.settings = SimpleNamespace(git_sha="abc1234")
    app.state.started_at = datetime.now(UTC)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method, path, body, status", [
    ("POST", "/v1/predict", SAMPLE, 200),
    ("POST", "/v1/predict", {**SAMPLE, "amount_sar": "lots"}, 422),
    ("GET", "/v1/health", None, 200),
    ("GET", "/v1/ready", None, 200),
    ("GET", "/v1/does-not-exist", None, 404),
    ("GET", "/v1/predict", None, 405),
])
def test_every_response_names_its_trace_and_model(ready_client, method, path, body, status):
    r = ready_client.request(method, path, json=body)
    assert r.status_code == status
    assert r.headers["X-Model-Version"] == "test-9"
    assert r.headers["X-Trace-Id"]
    if status >= 400:                                    # errors use the one envelope
        assert r.json()["error"]["trace_id"] == r.headers["X-Trace-Id"]


@pytest.mark.parametrize("status, code", [(404, "NOT_FOUND"), (405, "METHOD_NOT_ALLOWED")])
def test_routing_errors_have_stable_codes(ready_client, status, code):
    path, method = ("/v1/nope", "GET") if status == 404 else ("/v1/predict", "GET")
    r = ready_client.request(method, path)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


@pytest.mark.parametrize("bad_trace", ["has spaces", "x" * 65, "semi;colon", "<script>"])
def test_unsafe_caller_trace_id_is_replaced(ready_client, bad_trace):
    r = ready_client.post("/v1/predict", json=SAMPLE, headers={"X-Trace-Id": bad_trace})
    assert r.headers["X-Trace-Id"] != bad_trace
    assert GENERATED_TRACE.fullmatch(r.headers["X-Trace-Id"])
    assert r.json()["trace_id"] == r.headers["X-Trace-Id"]


def test_oversized_body_is_refused_before_parsing(ready_client):
    r = ready_client.post("/v1/predict", content=b"x" * (MAX_BODY_BYTES + 1),
                          headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert r.headers["X-Trace-Id"] == r.json()["error"]["trace_id"]


def test_crash_still_answers_with_trace_header(ready_client, monkeypatch):
    monkeypatch.setattr(FraudScorer, "score", lambda self, txn: 1 / 0)
    r = ready_client.post("/v1/predict", json=SAMPLE, headers={"X-Trace-Id": "crash-1"})
    assert r.status_code == 500
    assert r.headers["X-Trace-Id"] == "crash-1"
    assert r.json()["error"] == {"code": "INTERNAL_ERROR", "trace_id": "crash-1",
                                 "message": "Unexpected error; contact support with trace_id"}


def test_prediction_is_never_cached(ready_client):
    assert ready_client.post("/v1/predict", json=SAMPLE).headers["Cache-Control"] == "no-store"


def test_ready_reports_the_model_it_serves(ready_client):
    body = ready_client.get("/v1/ready").json()
    assert body["status"] == "ready"
    assert body["model_version"] == "test-9"


def test_every_request_log_line_names_trace_and_model(ready_client, capsys):
    from fraud_service.logging_setup import configure_logging

    configure_logging("INFO")
    ready_client.post("/v1/predict", json=SAMPLE, headers={"X-Trace-Id": "log-check-1"})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()
             if line.startswith("{")]
    mine = [line for line in lines if line.get("trace_id") == "log-check-1"]
    assert {line["event"] for line in mine} >= {"prediction_served", "http_request"}
    assert all(line["model_version"] == "test-9" for line in mine)
    assert not any("customer_id" in line or "amount_sar" in line for line in mine)


def test_openapi_documents_the_error_envelope(ready_client):
    spec = ready_client.get("/openapi.json").json()
    responses = spec["paths"]["/v1/predict"]["post"]["responses"]
    for status in ("422", "500", "503"):
        ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorEnvelope")
