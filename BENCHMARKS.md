# Benchmarks

Numbers I measured for this repository, with the method, the machine and the date. Nothing
here is copied from the lab guides. Re-run any of them with the command shown.

**Machines**
- **Laptop:** Windows 11 Home, Intel Core i7-14650HX (16 cores, 24 threads), 16 GB RAM,
  Python 3.12.10, one uvicorn worker, `OMP_NUM_THREADS=1`. Measured 24 November 2026.
- **CI runner:** GitHub Actions `ubuntu-latest`, 4 vCPU. The container numbers come from the
  `benchmarks` workflow (`scripts/bench_container.sh`); the run is linked under each table.

## Lab 2: API latency and the two traps (laptop)

| Measurement | Result |
|---|---|
| Model load (`SklearnModel.load`) | 0.61 s |
| First prediction on a cold artefact | 15.1 ms |
| Prediction after warm-up (median of 200) | 1.62 ms |
| `loadtest.py -n 300 -c 10` against `uvicorn` | p50 30.2 ms, p99 42.7 ms, 326 req/s, 0 errors |
| `loadtest.py -n 2000 -c 25` | p50 75.5 ms, p99 109.0 ms, 326 req/s, 0 errors |
| Async trap: 200 ms blocking call in `async def`, 40 requests at concurrency 10 | 8.1 s, **5.0 req/s** |
| The same call in a plain `def` | 0.8 s, **49.1 req/s** |

What it shows:
- Warm-up removes a first-request penalty roughly nine times the steady cost. The lifespan
  pays it before `/v1/ready` turns green.
- Throughput stays flat (326 req/s) from concurrency 10 to 25 while p50 grows: requests
  queue for the worker threads. More concurrency adds waiting, not capacity.
- Blocking inside `async def` serialises the whole server (40 × 0.2 s = 8 s). That is
  decision 3 in [DECISIONS.md](DECISIONS.md).

## Lab 6: answers from the JSON log alone (laptop)

Server started with `--no-access-log`, stdout sent to `service.log`, then 2,300 predictions
plus one request with `X-Trace-Id: my-trace-1`.

| Question | Answer from `service.log` |
|---|---|
| Median scoring latency (`prediction_served.latency_ms`) | 2.5 ms (p95 12.0 ms) over 2,301 events |
| Median server-side request latency (`http_request`, under load) | 66.1 ms |
| Every event of trace `my-trace-1` | exactly two: `prediction_served` (bucket 0.6, `v3.2.0`, 2.4 ms) and `http_request` (200, 3.4 ms) |
| Process start to `/v1/ready` 200 | 3.6 s; `model_loaded` reported 0.69 s |
| Started with `FRAUD_MODEL_PATH=/nope` | refused to start: `model artefact not found` |

## Batch extension (laptop, in-process)

| Measurement | Result |
|---|---|
| 256 transactions as one `POST /v1/predict:batch` (median of 20) | 7.8 ms |
| The same 256 as sequential `POST /v1/predict` calls (median of 3 runs) | 1,304 ms |
| Speed-up | about 166 times |

## Lab 3: the container (CI runner)

Final run on `main` after the supply-chain pull request (#5), using the same script:
[run 45309855953](https://github.com/aaturki/fraud-service/actions/runs/45309855953),
commit `bf2ce3a`, 24 November 2026, 4 vCPU runner.

| Measurement | Result |
|---|---|
| Naive image (Lab 3 `Dockerfile.naive`: `python:3.12`, `COPY . .`, dev extras): size | 712 MB |
| Naive image: cold build | 82.8 s |
| Production image (multi-stage, slim, non-root, no curl or pip): size | **184 MB** |
| Production image: cold build, no cache (includes the Debian security updates) | 59.3 s |
| Rebuild after a one-line edit in `routes.py` | **3.2 s** |
| `docker run` to `/v1/ready` 200 (2 workers, model load and warm-up) | 2.4 s |
| `/v1/predict`, 300 requests at concurrency 10 | p50 38.1 ms, p99 68.6 ms, 254 req/s, 0 errors |
| `/v1/predict`, 2,000 requests at concurrency 25 | p50 98.0 ms, p99 171.8 ms, 252 req/s, 0 errors |
| `/v1/predict:batch`, 256 items, 50 requests at concurrency 2 | p50 14.5 ms, p99 19.3 ms (about 30,000 transactions/s) |
| Memory after the load tests (`docker stats`) | 295 MiB |
| `docker stop` (SIGTERM to uvicorn as PID 1) | 0.6 s, exit code 0 |

GitHub's shared runners vary from run to run. The run before #5 (below) was on a faster
runner: same script, 381 req/s at concurrency 10. So compare sizes across runs, but compare
latencies only within one run.

Before the supply-chain pull request (#5) dropped `curl` and `pip` and applied the Debian
security updates, the same script measured a 182 MB image. That run was on 24 November 2026,
[run 45308947074](https://github.com/aaturki/fraud-service/actions/runs/45308947074). Its
cold build took 39.0 s and the rebuild after a one-line edit 1.3 s.

What it shows:
- Multi-stage on a slim base cuts the naive image by about three quarters.
- The rebuild after a code edit takes seconds because dependencies and the model sit in
  layers above the source and come from the cache.
- `docker stop` returns in under a second with exit code 0. Exec-form `CMD` makes uvicorn
  PID 1, so it receives SIGTERM and drains, instead of being killed after the 10 s timeout.

## Lab 4: the test suite (laptop)

| Measurement | Result |
|---|---|
| Fast suite, `pytest -m "not slow" --cov` | 145 tests in 9 s, 100% branch coverage |
| Full suite, including the golden file | 148 tests in 34 s |
| Golden file alone (5,000 rows, `test_golden_scores`) | 8.6 s; largest difference 5e-10 |
| Malformed corpus | 46 of 46 payloads rejected with 422 |

## Lab 5: the pipeline (CI runner)

| Job | First run on `main` (cold caches, Lab 5 reference) | Latest run on `main` |
|---|---|---|
| `secrets` (added in #2) | not present | 7 s |
| `lint` | 47 s | 44 s |
| `test` | 59 s | 52 s |
| `image-smoke` | 126 s | 64 s, now also the healthcheck and the compose stack |
| `image-scan` (added in #5) | not present | 67 s |
| `publish` | 41 s | 22 s |

First run: [45306194109](https://github.com/aaturki/fraud-service/actions/runs/45306194109).
Latest run measured: [45309845877](https://github.com/aaturki/fraud-service/actions/runs/45309845877).
`golden-guard` (added in #9) takes a few seconds.

The first run had no pip or layer cache. Later runs reuse the pip cache (`setup-python`) and
the GitHub Actions layer cache (`cache-from: type=gha`). The image build then only re-runs
the source layer, which is why the second image build is clearly faster.

## Image scan (CI runner)

| Scan | Result |
|---|---|
| First `image-scan` run (pull request #5) | 1 HIGH with a fix: CVE-2026-85091 in `zlib1g` |
| After applying Debian security updates in the runtime stage | 0 HIGH or CRITICAL with a fix; `.trivyignore` stays empty |
