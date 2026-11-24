"""GET /metrics: what a Prometheus scrape sees after real traffic."""
import json
import pathlib
import re

import pytest

from fraud_service.api.metrics import BUCKETS, Metrics

SAMPLE = json.loads(pathlib.Path("payloads/sample.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.integration


def _value(text: str, series: str) -> float:
    match = re.search(rf"^{re.escape(series)} (\S+)$", text, re.MULTILINE)
    assert match, f"missing series: {series}"
    return float(match.group(1))


def test_requests_are_counted_by_route_and_status(client_factory):
    client = client_factory(probability=0.93)
    for _ in range(3):
        client.post("/v1/predict", json=SAMPLE)
    client.post("/v1/predict", json={**SAMPLE, "amount_sar": "lots"})
    text = client.get("/metrics").text
    assert _value(text, 'http_requests_total{method="POST",route="/v1/predict",status="200"}') == 3
    assert _value(text, 'http_requests_total{method="POST",route="/v1/predict",status="422"}') == 1
    assert _value(text, 'fraud_decisions_total{decision="block"}') == 3


def test_latency_histogram_is_cumulative_and_consistent(client_factory):
    client = client_factory()
    for _ in range(5):
        client.post("/v1/predict", json=SAMPLE)
    text = client.get("/metrics").text
    route = 'route="/v1/predict"'
    buckets = [_value(text, f'http_request_duration_seconds_bucket{{{route},le="{b}"}}')
               for b in BUCKETS]
    assert buckets == sorted(buckets)                                 # cumulative
    total = _value(text, f'http_request_duration_seconds_bucket{{{route},le="+Inf"}}')
    assert total == _value(text, f"http_request_duration_seconds_count{{{route}}}") == 5
    assert _value(text, f"http_request_duration_seconds_sum{{{route}}}") > 0


def test_batch_decisions_are_counted_per_item(client_factory):
    client = client_factory(probability=0.93)
    items = [{**SAMPLE, "transaction_id": f"TXN-METRIC-{i:03d}"} for i in range(4)]
    client.post("/v1/predict:batch", json={"items": items})
    assert _value(client.get("/metrics").text, 'fraud_decisions_total{decision="block"}') == 4


def test_unknown_paths_share_one_series(client_factory):
    client = client_factory()
    for path in ("/v1/a", "/v1/b", "/wp-admin", "/.env"):
        client.get(path)
    text = client.get("/metrics").text
    assert _value(text, 'http_requests_total{method="GET",route="unmatched",status="404"}') == 4
    assert "/wp-admin" not in text and "/.env" not in text


def test_path_parameters_never_become_label_values():
    from fastapi.testclient import TestClient

    from fraud_service.api.app import create_app

    app = create_app()
    app.add_api_route("/v1/cases/{case_id}", lambda case_id: {"case": case_id})
    client = TestClient(app)
    for case_id in ("A-1", "B-2", "C-3"):
        client.get(f"/v1/cases/{case_id}")
    text = client.get("/metrics").text
    assert _value(text, 'http_requests_total{method="GET",route="/v1/cases/{case_id}",'
                        'status="200"}') == 3
    assert "A-1" not in text


def test_scrapes_do_not_count_themselves_and_are_not_cached(client_factory):
    client = client_factory()
    client.get("/metrics")
    r = client.get("/metrics")
    assert 'route="/metrics"' not in r.text
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["content-type"].startswith("text/plain; version=0.0.4")


def test_model_info_names_the_serving_version():
    metrics = Metrics()
    assert 'fraud_model_info{version="v3.2.0"} 1' in metrics.render("v3.2.0")
    assert "fraud_model_info" not in metrics.render(None)              # nothing loaded yet


def test_every_series_has_help_and_type():
    metrics = Metrics()
    metrics.observe_request("GET", "/v1/health", 200, 0.002)
    metrics.count_decisions(["allow"])
    text = metrics.render("v1")
    families = {line.split()[2] for line in text.splitlines() if line.startswith("# TYPE")}
    assert families == {"http_requests_total", "http_request_duration_seconds",
                        "fraud_decisions_total", "fraud_model_info"}
    assert text.count("# HELP") == len(families)
