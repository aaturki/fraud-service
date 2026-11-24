import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from fraud_service.api.schemas import (
    ErrorEnvelope,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadyResponse,
)
from fraud_service.logging_setup import get_logger
from fraud_service.service.scorer import FraudScorer

router = APIRouter()
log = get_logger(__name__)

# Documented in /docs so a consumer sees every failure shape before they hit one.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorEnvelope, "description": "INVALID_REQUEST: the body broke the contract"},
    500: {"model": ErrorEnvelope, "description": "INTERNAL_ERROR: quote the trace_id to support"},
    503: {"model": ErrorEnvelope, "description": "MODEL_UNAVAILABLE: still starting, retry"},
}


def get_scorer(request: Request) -> FraudScorer:
    """DI seam: tests override this one function to inject fakes."""
    scorer = getattr(request.app.state, "scorer", None)
    if scorer is None:                         # startup incomplete or failed
        raise HTTPException(status_code=503, detail="Model not ready",
                            headers={"Retry-After": "5"})
    return scorer


@router.post("/predict", response_model=PredictResponse, responses=ERROR_RESPONSES)
def predict(body: PredictRequest, request: Request, response: Response,
            scorer: Annotated[FraudScorer, Depends(get_scorer)]) -> PredictResponse:
    # Plain `def`: inference blocks, so FastAPI runs it in a worker thread.
    t0 = time.perf_counter()
    score = scorer.score(body.to_domain())
    log.info("prediction_served",
             decision=score.decision.value,
             probability_bucket=round(score.probability, 1),   # bucketed, never raw
             model_version=score.model_version,
             latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    # ABSENT by design: customer_id, amount, raw feature values
    response.headers["X-Model-Version"] = score.model_version
    response.headers["Cache-Control"] = "no-store"     # a risk decision is never reusable
    return PredictResponse(
        transaction_id=score.transaction_id,
        fraud_probability=round(score.probability, 6),
        decision=score.decision,
        model_version=score.model_version,
        trace_id=request.state.trace_id,
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness: the process is up. NO I/O here."""
    return HealthResponse(status="ok",
                          git_sha=request.app.state.settings.git_sha,
                          started_at=request.app.state.started_at)


@router.get("/ready", response_model=ReadyResponse, responses={503: ERROR_RESPONSES[503]})
def ready(request: Request) -> ReadyResponse:
    """Readiness: safe to receive traffic. Checks the model is loaded."""
    scorer = getattr(request.app.state, "scorer", None)
    if scorer is None:
        raise HTTPException(status_code=503, detail="warming up",
                            headers={"Retry-After": "5"})
    return ReadyResponse(status="ready", model_version=scorer.model.model_version,
                         checked_at=datetime.now(UTC))
