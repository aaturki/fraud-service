#!/usr/bin/env bash
# Container numbers for BENCHMARKS.md, measured where the image is really built: the CI runner.
#   bash scripts/bench_container.sh > bench.md        (needs docker, curl, python with httpx)
# Measures: naive versus production image (size, cold build), rebuild after a one-line code
# edit, start to ready, latency under load, a 256-item batch, memory, graceful stop.
set -euo pipefail
export DOCKER_BUILDKIT=1

now() { date +%s.%N; }
secs() { python3 -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.1f}')" "$1" "$2"; }
size_mb() { docker image inspect "$1" --format '{{.Size}}' | python3 -c "import sys; print(round(int(sys.stdin.read()) / 1e6))"; }

docker builder prune -af >/dev/null 2>&1 || true

# The Lab 3 naive image (python:3.12, COPY . ., dev extras), with only .git ignored, as in the lab.
naive_dir=$(mktemp -d)
cp labs/handouts/lab3/Dockerfile.naive "$naive_dir/Dockerfile.naive"
printf '.git\n' > "$naive_dir/Dockerfile.naive.dockerignore"
t0=$(now); docker build -q -f "$naive_dir/Dockerfile.naive" -t fraud:naive . >/dev/null; t1=$(now)
naive_build=$(secs "$t0" "$t1"); naive_size=$(size_mb fraud:naive)

t0=$(now); docker build -q --no-cache -t fraud:prod . >/dev/null; t1=$(now)
prod_build=$(secs "$t0" "$t1"); prod_size=$(size_mb fraud:prod)

echo "# benchmark: a one-line code edit" >> src/fraud_service/api/routes.py
t0=$(now); docker build -q -t fraud:edit . >/dev/null; t1=$(now)
rebuild=$(secs "$t0" "$t1")
git checkout -- src/fraud_service/api/routes.py

t0=$(now); docker run -d --name bench -p 8000:8000 fraud:prod >/dev/null
until curl -fsS localhost:8000/v1/ready >/dev/null 2>&1; do sleep 0.1; done; t1=$(now)
ready=$(secs "$t0" "$t1")

python3 - <<'PY'
import json
sample = json.load(open("payloads/sample.json"))
items = [{**sample, "transaction_id": f"TXN-BENCH-{i:04d}", "amount_sar": 10.0 + i * 37.5}
         for i in range(256)]
json.dump({"items": items}, open("/tmp/batch256.json", "w"))
PY
single_c10=$(python3 scripts/loadtest.py -n 300 -c 10 | tr '\n' ' ')
single_c25=$(python3 scripts/loadtest.py -n 2000 -c 25 | tr '\n' ' ')
batch=$(python3 scripts/loadtest.py -n 50 -c 2 --url http://localhost:8000/v1/predict:batch \
        --body /tmp/batch256.json | tr '\n' ' ')
mem=$(docker stats --no-stream --format '{{.MemUsage}}' bench)
t0=$(now); docker stop bench >/dev/null; t1=$(now); stop=$(secs "$t0" "$t1")
exit_code=$(docker inspect bench --format '{{.State.ExitCode}}')

cat <<EOF
## Container benchmarks

Measured by \`scripts/bench_container.sh\` on the GitHub Actions runner: $(nproc) vCPU,
$(free -g | awk '/Mem:/ {print $2}') GB RAM, Docker $(docker version --format '{{.Server.Version}}'),
commit \`${GITHUB_SHA:-local}\`, $(date -u +%Y-%m-%dT%H:%MZ).

| Measurement | Result |
|---|---|
| Naive image (Lab 3 \`Dockerfile.naive\`): size | ${naive_size} MB |
| Naive image: cold build | ${naive_build} s |
| Production image (multi-stage, slim, non-root): size | ${prod_size} MB |
| Production image: cold build, no cache | ${prod_build} s |
| Rebuild after a one-line edit in \`routes.py\` | ${rebuild} s |
| \`docker run\` to \`/v1/ready\` 200 (2 workers, model load and warm-up) | ${ready} s |
| \`/v1/predict\`, 300 requests, concurrency 10 | ${single_c10} |
| \`/v1/predict\`, 2,000 requests, concurrency 25 | ${single_c25} |
| \`/v1/predict:batch\` with 256 items, 50 requests, concurrency 2 | ${batch} |
| Memory after the load test (\`docker stats\`) | ${mem} |
| \`docker stop\` (SIGTERM to uvicorn as PID 1) | ${stop} s, exit code ${exit_code} |
EOF
