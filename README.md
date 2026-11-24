# Raqib · fraud-scoring service

[![ci](https://github.com/aaturki/fraud-service/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aaturki/fraud-service/actions/workflows/ci.yml)
[![image](https://img.shields.io/badge/image-ghcr.io%2Faaturki%2Ffraud--service-blue)](https://github.com/aaturki/fraud-service/pkgs/container/fraud-service)

A containerised machine-learning service that scores card transactions for fraud risk and
answers **allow**, **review** or **block**.

Built in the training program **SDA-AIE-113 · Software Engineering Practices for AI Systems**
at [SDAIA Academy](https://github.com/SDAIAAcademy), November 2026. Workshop:
[aie113.ibrahimalshehri.sa](https://aie113.ibrahimalshehri.sa) · starter repository:
[snow10100/fraud-service](https://github.com/snow10100/fraud-service).

## What it does

Raqib (رقيب) is the fraud-scoring capability of a Saudi digital-payments provider. The
payment platform calls it once per card transaction, before authorising it. The service
turns the transaction into model features, scores it with the trained model the
data-science team handed over (`models/fraud_xgb_v3.joblib`, version `v3.2.0`) and applies
the business policy. A probability at or above the block threshold (0.85 by default) means
**block**. The 0.15 below that means **review** by an analyst. Anything lower means
**allow**.

Every answer names the model version and a trace id, so any decision can be tied to one log
line and one artefact. **All data in this repository is synthetic**: no real customer or
transaction appears anywhere.

## Run it

### With Docker (recommended)

    git clone https://github.com/aaturki/fraud-service.git
    cd fraud-service
    docker compose up --build -d --wait        # API + Redis, gated on both healthchecks
    curl -s localhost:8000/v1/ready
    curl -s localhost:8000/v1/predict -H "content-type: application/json" -d @payloads/sample.json
    docker compose down -v

Or run the image CI published, tagged with the commit SHA (and `main`):

    docker run --rm -p 8000:8000 ghcr.io/aaturki/fraud-service:main

### Without Docker (Python 3.12 or newer)

    python -m venv .venv
    source .venv/bin/activate                  # Windows PowerShell: .venv\Scripts\Activate.ps1
    pip install -e ".[dev]"
    pre-commit install                         # secret scan and file checks before each commit
    cp configs/settings.example.env .env       # Windows: Copy-Item configs\settings.example.env .env
    uvicorn fraud_service.api.app:create_app --factory

Interactive documentation: <http://localhost:8000/docs>. On Windows use `curl.exe`, not the
PowerShell `curl` alias, and run the commands behind a Makefile target directly (`make` is not
available outside WSL).

## Architecture

    api        FastAPI routes, wire schemas, error envelope, metrics. api/app.py is the
     │         composition root: the only place concrete classes are wired together.
     ▼
    adapters   SklearnModel: the ONLY module that imports scikit-learn, joblib or pandas.
     │
     ▼
    service    FraudScorer use-case and the Model protocol it depends on.
     │
     ▼
    domain     Transaction, FeatureVector, decision policy: pure Python, no I/O.

Imports point inward only. The contract is declared in `pyproject.toml` and enforced by
`lint-imports` on every pull request.

The model sits behind a `Model` protocol (`predict_proba`, `predict_proba_many`), so the
service never knows it is talking to scikit-learn. Tests inject a constant fake. Moving to
ONNX or a remote model server means one new adapter and one changed line in the composition
root.

## API

| Endpoint | Purpose |
|---|---|
| `POST /v1/predict` | Score one transaction |
| `POST /v1/predict:batch` | Score 1 to 256 transactions; each item is validated on its own |
| `GET /v1/health` | Liveness: the process is up (no I/O) |
| `GET /v1/ready` | Readiness: the model is loaded and warmed up; names the model version |
| `GET /metrics` | Prometheus metrics: requests, latency histogram, decisions, model |
| `GET /docs` | OpenAPI documentation, including every error shape |

**Request** (`payloads/sample.json`). `extra="forbid"` refuses any unknown field.

| Field | Contract |
|---|---|
| `transaction_id` | text, 8 to 64 characters |
| `amount_sar` | a JSON **number**, greater than 0, at most 1,000,000 (text and booleans are refused) |
| `channel` | one of `pos`, `ecom`, `atm`, `transfer` |
| `merchant_category` | text, 2 to 40 characters, at least 2 visible |
| `customer_id` | text, 4 to 64 characters |
| `timestamp` | ISO 8601 text **with an offset**, for example `2026-07-05T03:30:00+03:00` |

**Response**

    {"transaction_id": "TXN-2026-00042", "fraud_probability": 0.62614, "decision": "allow",
     "model_version": "v3.2.0", "trace_id": "my-trace-1"}

**Headers on every response.**
- `X-Trace-Id`: the caller's value is kept if it matches `[A-Za-z0-9._:-]{1,64}`, otherwise
  a new one is generated.
- `X-Model-Version`, and `X-Response-Time-Ms`.
- Predictions also carry `Cache-Control: no-store`.

**Errors** share one envelope and never echo input values:

    {"error": {"code": "INVALID_REQUEST", "message": "Request body failed validation",
               "trace_id": "9f2c41d07a3b5e18",
               "details": [{"field": "amount_sar", "problem": "Input should be a valid number"}]}}

| Code | Status | When |
|---|---|---|
| `INVALID_REQUEST` | 422 | The body broke the contract (`details` lists the fields) |
| `NOT_FOUND` | 404 | Unknown path |
| `METHOD_NOT_ALLOWED` | 405 | Wrong method for a known path |
| `PAYLOAD_TOO_LARGE` | 413 | Body above 256 KB, refused before parsing |
| `MODEL_UNAVAILABLE` | 503 | Still starting; retry after the `Retry-After` seconds |
| `INTERNAL_ERROR` | 500 | Unexpected failure; quote the `trace_id` to support |

**Batch.** `{"items": [...]}` with 1 to 256 transactions. Each item is validated like a
`/v1/predict` body. Valid items are scored in one model call. Invalid items come back in place
with `"status": "rejected"` and field-level `details`. The answer is 200 with a `summary`
whenever the envelope itself is valid.

## Configuration

Typed settings (`src/fraud_service/config.py`), read from `FRAUD_*` environment variables or
a local `.env`, and validated at start-up. A bad value stops the service with the field name,
instead of a 500 hours later. `os.environ` is read nowhere else, and an unknown `FRAUD_*` key
is an error.

| Variable | Default | Meaning |
|---|---|---|
| `FRAUD_MODEL_PATH` | required | Path to the model bundle; must exist |
| `FRAUD_BLOCK_THRESHOLD` | `0.85` | Scores at or above are blocked; must stay in the risk-approved 0.5 to 0.99 |
| `FRAUD_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `FRAUD_GIT_SHA` | `dev` | Injected by CI at build time; reported by `/v1/health` |
| `FRAUD_REDIS_URL` | `redis://localhost:6379/0` | The compose stack's Redis |
| `FRAUD_REGISTRY_TOKEN` | unset | Secret, only from the platform's secret store; never logged |

Secrets are never committed. `configs/settings.example.env` documents every knob, and `.env`
is git-ignored and docker-ignored. A secret is looked for at three points, each earlier than
the next would be:

1. **Before each commit:** the gitleaks hook in `.pre-commit-config.yaml` scans what you are
   about to commit. CI proves the hook works: it stages a freshly generated fake token and
   expects a refusal.
2. **On every push:** GitHub secret scanning and push protection are on for this repository.
3. **On every pull request:** the `secrets` job runs gitleaks over the whole history.

The secret-leak drill and the response runbook are in [INCIDENT.md](INCIDENT.md).

## Logs and metrics

Every log line is one JSON object on stdout, in UTC, with the request's `trace_id`.

| Event | Carries |
|---|---|
| `settings_effective` | What the process really runs with (no secrets) |
| `model_loaded` | Model version and load time |
| `http_request` | Method, path, status, latency |
| `prediction_served` | Decision, probability bucketed to 0.1, model version, latency. Never the customer id, the amount or raw features |
| `batch_served` | Item counts and decisions only |

Sensitive keys (`token`, `password`, `secret`, `authorization`, ...) are masked even if
someone logs them. Example: every event of one request.

    python -c "import json,sys; [print(l, end='') for l in open('service.log') if json.loads(l).get('trace_id') == 'my-trace-1']"

`GET /metrics` serves `http_requests_total`, the `http_request_duration_seconds` histogram,
`fraud_decisions_total` and `fraud_model_info`. Labels are route templates, so random URLs
cannot create unbounded series.

## Tests

    pytest -m "not slow" --cov --cov-fail-under=80     # every commit: 145 tests, about 9 s, 100% branch coverage
    pytest                                             # everything, including the 5,000-row golden file
    ruff check src tests && mypy src/fraud_service && lint-imports

Three levels: `tests/unit` (pure logic, no I/O), `tests/integration` (the app through
`TestClient`, with a fake model injected), and `tests/behavioural` (the real artefact). What
the behavioural tests claim about the model:

- **Invariance:** casing and stray spaces in the merchant category do not move the score.
- **Invariance:** the customer id and the transaction id do not move the score.
- **Direction:** all else equal, a much larger amount never lowers the fraud probability.
- **Consistency:** the batch path returns exactly the one-by-one probabilities.
- **Golden file:** all 5,000 reference rows reproduce within 1e-6. This is the skew tripwire; it is slow, so it runs nightly.

All 46 payloads in `payloads/malformed/` are rejected with 422. That is the workshop's 40
plus the 6 cases added by contract 1.1 ([CHANGELOG.md](CHANGELOG.md)), and a test stops the
corpus from shrinking.

## Pipeline

| Job | Runs on | What it proves |
|---|---|---|
| `secrets` | PR, main | gitleaks finds no secret anywhere in the history |
| `pre-commit` | PR, main | Every pre-commit hook passes on the whole repository, and the gitleaks hook refuses a freshly generated fake token |
| `golden-guard` | PR, main | A golden file never changes without a `docs/GOLDEN_CHANGELOG.md` entry |
| `lint` | PR, main | Ruff, mypy and the layer contract (`lint-imports`) |
| `test` | PR, main | The fast suite with branch coverage of 80% or more; coverage report uploaded |
| `image-smoke` | PR, main (after lint and test) | The image builds under the 600 MB budget and serves predictions. Also checks the headers and the 422 envelope, the non-root user, no curl or pip in the image, a `healthy` healthcheck and the compose stack |
| `image-scan` | PR, main (after lint and test) | Trivy finds no fixable HIGH or CRITICAL vulnerability; full report and CycloneDX SBOM uploaded |
| `publish` | main only | Pushes `ghcr.io/aaturki/fraud-service:<commit-sha>` and `:main`; never `latest` alone |
| `nightly` | every night | The full suite, including the golden file |
| `benchmarks` | by hand, Dockerfile changes | The container numbers in [BENCHMARKS.md](BENCHMARKS.md) |

`main` is protected. A pull request is required, the checks `secrets`, `golden-guard`,
`lint`, `test`, `image-smoke` and `image-scan` must pass, admins are included, and force
pushes are blocked. `pre-commit` runs on every pull request but is not a required check.
Evidence is
[pull request #1](https://github.com/aaturki/fraud-service/pull/1), the Lab 5 exercise. It
broke the layer contract and moved a feature boundary (`hour < 6` to `hour <= 6`), and
`lint` and `test` blocked it:

The failing run is [45306753157](https://github.com/aaturki/fraud-service/actions/runs/45306753157). `lint` stopped at Ruff (`I001`, the stray import), and `test` failed `test_night_flag_boundaries[6-0]`.

Every action is pinned to a full commit SHA and both base images to a digest. Dependabot
proposes the updates, which go through the same gates.

## Benchmarks, decisions, history

- [BENCHMARKS.md](BENCHMARKS.md): the numbers I measured, with the method, the machine and the date.
- [DECISIONS.md](DECISIONS.md): the engineering decisions and the alternatives I weighed.
- [CHANGELOG.md](CHANGELOG.md): the contract versions. [INCIDENT.md](INCIDENT.md): the secret-leak runbook.
- [docs/GOLDEN_CHANGELOG.md](docs/GOLDEN_CHANGELOG.md): every golden-file change and its reason.

## Extensions

Beyond the mandatory scope, each with tests:

1. **Batch endpoint:** `POST /v1/predict:batch`, up to 256 items with per-item results. Try it: `curl -s localhost:8000/v1/predict:batch -H "content-type: application/json" -d @payloads/batch_sample.json` (two valid items, one with a text amount).
2. **Stricter firewall:** contract 1.1 refuses text or boolean amounts and timestamps without an offset; the corpus grows from 40 to 46 payloads; documented in [CHANGELOG.md](CHANGELOG.md).
3. **Metrics endpoint:** `GET /metrics` with a request counter and a latency histogram.
4. **Image scan gate:** Trivy pinned by SHA, failing the PR on fixable HIGH or CRITICAL issues, with a reviewed `.trivyignore`. It caught CVE-2026-85091 on its first run, and the image now applies the Debian fix.
5. **Golden regeneration workflow:** `make regen-golden REASON="..."` refuses to run without a reason or under an unchanged model version. A pull request template carries an evidence checklist, and the `golden-guard` job enforces the changelog.

## Troubleshooting

- **The service refuses to start:** read the message. `model artefact not found` means `FRAUD_MODEL_PATH` is wrong, and `block_threshold` means the value is outside 0.5 to 0.99. A refusal at start-up is the intended behaviour.
- **Scoring takes minutes on a many-core machine (often WSL):** set `OMP_NUM_THREADS=1`.
- **`docker pull` is refused:** the package must be public, under Package settings, Change visibility.
- **Windows blocks a program (`WinError 4551`, or a Smart App Control notice):** Smart App Control refuses unsigned programs, such as the `pytest.exe` launcher, the native library behind `lint-imports` and the pre-commit hooks. Nothing is wrong with the code. Run `python -m pytest`, skip `pre-commit install` on that machine, and rely on CI, which runs `lint-imports` and every hook on Linux for each pull request. Turning Smart App Control off is not needed.

## Repository layout

| Path | What |
|---|---|
| `src/fraud_service/` | The service: `domain/`, `service/`, `adapters/`, `api/`, `config.py`, `logging_setup.py` |
| `tests/` | `unit/`, `integration/`, `behavioural/` |
| `payloads/` | `sample.json` and the 46-payload malformed corpus |
| `data/`, `models/` | Synthetic transactions, golden scores, the model artefact (never edited by hand) |
| `scripts/` | Load test, async-trap demo, golden check and regeneration, container benchmarks |
| `configs/` | `settings.example.env` (committed) and `dev.env` (non-secret compose settings) |
| `labs/` | The workshop's lab guides and handouts; see [labs/README.md](labs/README.md) |

## Author

Turki · [github.com/aaturki](https://github.com/aaturki). Built in SDA-AIE-113 at SDAIA
Academy, November 2026.
