"""POST /v1/predict:batch: up to 256 items, and a defined answer when some are bad."""
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from fraud_service.api.app import create_app
from fraud_service.api.schemas import MAX_BATCH_ITEMS

SAMPLE = json.loads(pathlib.Path("payloads/sample.json").read_text(encoding="utf-8"))
URL = "/v1/predict:batch"

pytestmark = pytest.mark.integration


def _txn(n: int, **patch: object) -> dict:
    return {**SAMPLE, "transaction_id": f"TXN-BATCH-{n:04d}", **patch}


def test_every_valid_item_is_scored_in_request_order(client_factory):
    r = client_factory(probability=0.93).post(URL, json={"items": [_txn(i) for i in range(3)]})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == {"total": 3, "scored": 3, "rejected": 0}
    assert [item["index"] for item in body["results"]] == [0, 1, 2]
    assert [item["transaction_id"] for item in body["results"]] == \
        ["TXN-BATCH-0000", "TXN-BATCH-0001", "TXN-BATCH-0002"]
    assert {item["decision"] for item in body["results"]} == {"block"}
    assert body["model_version"] == "test-1"
    assert body["trace_id"] == r.headers["X-Trace-Id"]


def test_bad_items_are_reported_in_place_and_do_not_sink_the_batch(client_factory):
    items = [_txn(0), _txn(1, amount_sar="249.99"), 42, _txn(3), {"channel": "ecom"}]
    r = client_factory().post(URL, json={"items": items})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == {"total": 5, "scored": 2, "rejected": 3}
    status = [item["status"] for item in body["results"]]
    assert status == ["scored", "rejected", "rejected", "scored", "rejected"]
    assert [d["field"] for d in body["results"][1]["details"]] == ["amount_sar"]
    assert body["results"][2]["details"][0]["field"] == "item"      # not even an object
    assert "transaction_id" in {d["field"] for d in body["results"][4]["details"]}
    assert body["results"][1]["decision"] is None


def test_all_items_rejected_is_still_a_valid_answer(client_factory):
    r = client_factory().post(URL, json={"items": [{"nope": 1}, "x"]})
    assert r.status_code == 200
    assert r.json()["summary"] == {"total": 2, "scored": 0, "rejected": 2}


def test_rejections_never_echo_values(client_factory):
    r = client_factory().post(URL, json={"items": [_txn(0, amount_sar=-987654.0)]})
    assert "987654" not in r.text


@pytest.mark.parametrize(("count", "status"), [(0, 422), (1, 200), (MAX_BATCH_ITEMS, 200),
                                           (MAX_BATCH_ITEMS + 1, 422)])
def test_batch_size_limits(client_factory, count, status):
    r = client_factory().post(URL, json={"items": [_txn(i) for i in range(count)]})
    assert r.status_code == status
    if status == 422:
        assert r.json()["error"]["code"] == "INVALID_REQUEST"
        assert r.json()["error"]["details"][0]["field"] == "items"


@pytest.mark.parametrize("body", [{"items": [], "debug": True}, {"items": "all"}, [SAMPLE], {}])
def test_the_batch_envelope_itself_is_strict(client_factory, body):
    r = client_factory().post(URL, json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_batch_headers_match_single_predictions(client_factory):
    r = client_factory().post(URL, json={"items": [_txn(0)]})
    assert r.headers["X-Model-Version"] == "test-1"
    assert r.headers["Cache-Control"] == "no-store"


def test_batch_waits_for_the_model_like_predict():
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.post(URL, json={"items": [_txn(0)]})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "MODEL_UNAVAILABLE"
