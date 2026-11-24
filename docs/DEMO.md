# Three-minute demo script

The workshop's lightning demo asks for one valid request, one rejected request, and the green
pipeline. This script runs on the presenter's Windows laptop with Python only. The container
itself is built, health-checked and smoke-tested by CI on every pull request, and the demo
shows that from the Actions tab.

Commands are for Windows PowerShell, run from the repository folder. Use `curl.exe`, not the
PowerShell `curl` alias, and keep the quotes in `"@file"`: `@` means something to PowerShell.

## Before the demo (once)

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -e ".[dev]"
    $env:FRAUD_MODEL_PATH = "models/fraud_xgb_v3.joblib"
    python -m uvicorn fraud_service.api.app:create_app --factory --port 8000

Leave the server running in this terminal and open a second one for the requests. Open two
browser tabs: the repository's Actions tab, and the README at its Pipeline section.

## 0:00 Ready (15 s)

    curl.exe -s localhost:8000/v1/ready

Say: readiness names the model version, and the container's healthcheck probes this endpoint,
not `/v1/health`.

## 0:15 One valid request (40 s)

    curl.exe -s -i localhost:8000/v1/predict -H "content-type: application/json" -H "X-Trace-Id: demo-1" -d "@payloads/sample.json"

Point at four things:
- the decision and the probability: `allow`, 0.626;
- the `X-Trace-Id: demo-1` and `X-Model-Version: v3.2.0` headers;
- `Cache-Control: no-store`;
- `reasons` is empty: an allow needs none and costs no extra model call.

## 0:55 An alert, with its reasons (35 s)

    curl.exe -s localhost:8000/v1/predict -H "content-type: application/json" -d "@payloads/demo_block.json"

A 9,500 SAR transfer at 02:10 UTC: `block`, 0.879. The reasons, strongest first, are the amount
(0.352), the channel (0.102) and the hour (0.062). Say what an effect means: how much lower the
score would be if that one field were typical. A reason names a field, never its value.

## 1:30 One rejected request (30 s)

    curl.exe -s localhost:8000/v1/predict -H "content-type: application/json" -d "@payloads/malformed/amount_as_string.json"

Point at the envelope: `INVALID_REQUEST`, the field name `amount_sar`, the `trace_id`, and no
echo of the value. Contract 1.1 refuses an amount sent as text instead of guessing.

## 2:00 The pipeline (45 s)

- The Actions tab: the latest run on `main` is green: `secrets`, `pre-commit`, `golden-guard`,
  `lint`, `test`, `image-smoke`, `image-scan` and `publish`.
- The package page: the image is tagged with its commit SHA. Optional, if there is time:
  `gh attestation verify oci://ghcr.io/aaturki/fraud-service:<commit-sha> --owner aaturki`.
- The README's Pipeline section: the screenshot of pull request #1, which branch protection
  refused to merge. It was then fixed on its own branch, passed every check and was merged.

## 2:45 Close (15 s)

Stop the server with `Ctrl+C`. Say: everything you saw is checked on every pull request; the
numbers are in BENCHMARKS.md and the reasoning in DECISIONS.md.
