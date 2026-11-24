# Engineering decisions

Each entry gives the decision, the alternatives I weighed, and the evidence behind the choice.

## 1. The model is baked into the image, not pulled at start-up

The artefact (`models/fraud_xgb_v3.joblib`, 226 KB) is copied into its own image layer,
between the dependencies and the source code. I considered downloading it from a model
registry at start-up, using `FRAUD_REGISTRY_TOKEN`. That would make every pod start depend on
the registry and a secret, and two pods started a minute apart could serve different models.
Baking it in means an image digest identifies the code **and** the model. The rollback is
"run the previous SHA tag", and the start-up path has nothing to fail but the file itself,
which `Settings` checks before the server accepts traffic. The cost is a rebuild on every
retrain. Because the model layer sits below the source layer, the cost is small: a code-only
rebuild took 1.3 to 3.2 s in CI ([BENCHMARKS.md](BENCHMARKS.md)).

## 2. The threshold is validated configuration; the review band is domain policy

The block threshold is a business decision that risk officers change without a release, so it
lives in `FRAUD_BLOCK_THRESHOLD`. `Settings` types and validates it, and refuses anything
outside the risk-approved 0.5 to 0.99. A typo such as `8.5` stops the service at start-up
instead of blocking every transaction. I rejected two alternatives. A constant in code would
need a deployment to tune. An attribute of the model artefact would tie a business rule to a
data-science release. The shape of the policy, a review band 0.15 wide below the threshold,
is a pure function in `domain/policies.py`. A risk officer can read it and sign it off, and
unit tests pin both boundaries.

## 3. The predict route is a plain `def`, not `async def`

Scoring is CPU-bound, blocking work inside scikit-learn. Inside `async def` it would run on
the event loop and stall every other request, health checks included. As a plain `def`,
FastAPI runs it in its worker thread pool. I measured the trap with `scripts/async_trap.py`
(the same 200 ms blocking call, 40 requests at concurrency 10): **5.0 req/s** as `async def`
against **49.1 req/s** as `def`. An `async def` route with `run_in_threadpool` would work too,
but it adds ceremony for the same result. A process pool would only pay off if scoring took
far longer than its 1.6 ms.

## 4. The wire contract is strict at the edge, not normalised inside

`PredictRequest` uses `extra="forbid"`, and contract 1.1 made amounts strict numbers and
timestamps offset-aware ISO 8601 text. I measured that 1.0.0 silently accepted `"249.99"`,
`true` (scored as one riyal), naive timestamps, date-only strings and Unix numbers. The
alternative was to coerce them, for example by assuming UTC for a naive time. But the hour
is a model feature (`hour_of_day`, `is_night`): a wrong guess changes the score without
anyone noticing. Refusing with `422` and the field name turns an upstream serialisation bug
into a visible error. It is a breaking change for sloppy callers, so it is versioned and
documented in [CHANGELOG.md](CHANGELOG.md), and the malformed corpus grew from 40 to 46
payloads.

## 5. A batch answers per item, and only the envelope can fail as a whole

`POST /v1/predict:batch` validates each item like a `/v1/predict` body and returns `200`, with
every item scored or rejected in its original position. I weighed two alternatives.
All-or-nothing `422` is simpler, but one typo would block 255 good transactions and push
callers into retry loops. `207 Multi-Status` is accurate but rarely handled well by HTTP
clients. The envelope itself stays strict (1 to 256 items, no unknown fields). Valid items
go through `predict_proba_many`, one DataFrame and one pipeline call. A behavioural test
proves it equals one-by-one scoring, and it is about 166 times faster than 256 single calls
in-process.

## 6. The supply chain is pinned and the scan gate fixes rather than ignores

In March 2026, 76 of 77 version tags of `aquasecurity/trivy-action` were moved onto
credential-stealing commits, because a tag is a movable pointer. Every action here is
therefore pinned to a full commit SHA, and both base images to a digest. Dependabot proposes
updates through the same gates, so the pins do not go stale. The Trivy gate fails on HIGH or
CRITICAL issues that have a fix. On its first run it found CVE-2026-85091 in `zlib1g`. I could
have added that CVE to `.trivyignore`. Instead the runtime stage applies the Debian security
update, because the fix existed and the ignore file is reserved for documented, reviewed
exceptions. The image also dropped `curl` and `pip`: the healthcheck uses Python's
`urllib`, so there are fewer binaries to patch and the image is 184 MB.

## 7. Metrics without a new dependency, accepting per-worker numbers

`/metrics` renders the Prometheus text format from a small thread-safe registry
(`api/metrics.py`). `prometheus_client` is the standard choice. But a new runtime dependency
means a new lock entry, more image surface and more scan findings, for four metric families.
The known limitation is the same one the official client has without its multiprocess mode:
each of the two uvicorn workers keeps its own numbers, and a scrape reads one of them.
Labels use route templates and one `unmatched` series for unknown paths. This keeps
cardinality bounded even when a scanner sends random URLs.

## 8. Secrets are caught before the commit, and CI proves the catcher works

A scanner that only runs in CI finds a secret after it has left the laptop. By then it is in
a pushed commit, and step 1 of [INCIDENT.md](INCIDENT.md) applies: rotate it. So gitleaks
also runs as a pre-commit hook, on exactly what is about to be committed, at the same release
as the CI scan. A local hook alone is not enough, though. It can be skipped with
`--no-verify`, never installed, or blocked by the operating system: Windows Smart App Control
refuses the hook programs on my laptop. So three layers stay. GitHub push protection refuses
known token formats at the push, the `secrets` job scans the whole history on every pull
request, and the `pre-commit` job stages a freshly generated fake GitHub token and fails if
the hook ever stops refusing it. I weighed a pre-push hook instead: it catches the secret one
step later, when it already sits in a local commit that has to be rewritten.
