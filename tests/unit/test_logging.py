"""The log line is a contract too: JSON, correlated, and never carrying a secret."""
import json

import pytest
import structlog

from fraud_service.logging_setup import configure_logging


def _last_json_line(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


@pytest.mark.unit
def test_log_lines_are_json_and_carry_the_bound_trace_id(capsys):
    configure_logging("INFO")
    structlog.contextvars.bind_contextvars(trace_id="trace-unit-1")
    try:
        structlog.get_logger("test").info("prediction_served", probability_bucket=0.6)
    finally:
        structlog.contextvars.clear_contextvars()
    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "prediction_served"
    assert line["trace_id"] == "trace-unit-1"
    assert line["level"] == "info"
    assert line["timestamp"].endswith("Z")          # always UTC


@pytest.mark.unit
@pytest.mark.parametrize("key", ["token", "Password", "registry_token", "card_number"])
def test_sensitive_keys_leave_masked(capsys, key):
    configure_logging("INFO")
    structlog.get_logger("test").info("debug", **{key: "abc123-secret"})
    out = capsys.readouterr().out
    assert "abc123-secret" not in out
    assert _last_json_line(out)[key] == "***MASKED***"
