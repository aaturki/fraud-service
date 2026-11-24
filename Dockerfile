# Base image pinned by digest: a rebuild uses the same bits; Dependabot proposes the updates.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# ---------- Stage 1: builder ----------
FROM ${PYTHON_IMAGE} AS builder

# If a dependency ever needs compiling, install build-essential HERE.
# Whatever this stage needs only for building never reaches the runtime stage.
COPY requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock \
    && /opt/venv/bin/pip uninstall --yes pip      # nothing is installed at runtime

# ---------- Stage 2: runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

# Debian security fixes published after the pinned base image was built (the scan gate
# found CVE-2026-85091 in zlib1g on 24 Nov 2026). Drop this line once Dependabot moves the
# digest to an official image that already contains the fixes.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Non-root user: the first thing any security review checks. No curl and no pip in the
# final image: fewer binaries, fewer CVEs to triage; the healthcheck uses Python itself.
RUN useradd --create-home --uid 10001 appuser \
    && python -m pip uninstall --yes pip

WORKDIR /app

# 1) Dependencies: hundreds of MB, change rarely => cached across code edits
COPY --from=builder /opt/venv /opt/venv

# 2) Model: changes on retrain, not on every commit
COPY models/fraud_xgb_v3.joblib /models/fraud_xgb_v3.joblib

# 3) Source: a few KB, changes every commit => keep it LAST
COPY src/ /app/src

ARG GIT_SHA=dev
LABEL org.opencontainers.image.title="raqib-fraud-service" \
      org.opencontainers.image.description="Raqib fraud-scoring API (SDA-AIE-113, SDAIA Academy)" \
      org.opencontainers.image.source="https://github.com/aaturki/fraud-service" \
      org.opencontainers.image.revision=$GIT_SHA
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    FRAUD_MODEL_PATH=/models/fraud_xgb_v3.joblib \
    FRAUD_GIT_SHA=$GIT_SHA

USER appuser
EXPOSE 8000

# Readiness-based healthcheck: /ready, not /health. urlopen raises on a 503, so "warming
# up" counts as unhealthy, exactly like curl -f did.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/ready', timeout=2)"]

# Exec form => uvicorn is PID 1 => it receives SIGTERM => graceful shutdown
CMD ["uvicorn", "fraud_service.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
