# Three-minute demo script

What the project brief asks for:
1. Start the stack.
2. Send one valid and one invalid request.
3. Show the green pipeline and the blocked pull request.

Commands are for Linux, macOS or WSL. On Windows PowerShell use `curl.exe`.

## 0:00 Start the stack (30 s)

    docker compose up --build -d --wait
    docker compose ps                     # fraud-api and feature-cache both "healthy"

Say: the API waits for Redis to be healthy, and its own healthcheck probes `/v1/ready`, not
`/v1/health`.

## 0:30 One valid request (30 s)

    curl -s -i localhost:8000/v1/predict -H "content-type: application/json" \
         -H "X-Trace-Id: demo-1" -d @payloads/sample.json

Point at three things:
- the decision and the probability;
- the `X-Model-Version` and `X-Trace-Id: demo-1` headers;
- `Cache-Control: no-store`.

## 1:00 One invalid request (30 s)

    curl -s localhost:8000/v1/predict -H "content-type: application/json" \
         -d @payloads/malformed/amount_as_string.json

Point at the envelope: `INVALID_REQUEST`, the field name `amount_sar`, the `trace_id`, and no
echo of the value. Optional: the batch keeps going past bad items.

    curl -s localhost:8000/v1/predict:batch -H "content-type: application/json" \
         -d @payloads/batch_sample.json

## 1:30 The logs and the metrics (30 s)

    docker compose logs fraud-api | grep demo-1      # every event of that one request, as JSON
    curl -s localhost:8000/metrics | grep fraud_

## 2:00 The pipeline (45 s)

- Open the Actions tab. The latest run on `main` is green: `secrets`, `golden-guard`, `lint`,
  `test`, `image-smoke`, `image-scan` and `publish`.
- Open the package page. The image is tagged with the commit SHA.
- Open pull request #1, the Lab 5 exercise. `lint` and `test` failed and branch protection
  blocked the merge. Show the screenshot in the README.

## 2:45 Close (15 s)

    docker compose down -v

Say: everything you saw is checked on every pull request; the numbers are in BENCHMARKS.md
and the reasoning in DECISIONS.md.
