import time
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError

from fraud_service.api.schemas import (
    BatchItemResult,
    BatchRequest,
    BatchResponse,
    BatchSummary,
    ErrorEnvelope,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadyResponse,
    problems,
)
from fraud_service.domain.entities import Transaction
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
    request.app.state.metrics.count_decisions([score.decision.value])
    response.headers["X-Model-Version"] = score.model_version
    response.headers["Cache-Control"] = "no-store"     # a risk decision is never reusable
    return PredictResponse(
        transaction_id=score.transaction_id,
        fraud_probability=round(score.probability, 6),
        decision=score.decision,
        model_version=score.model_version,
        trace_id=request.state.trace_id,
    )


@router.post("/predict:batch", response_model=BatchResponse, responses=ERROR_RESPONSES)
def predict_batch(body: BatchRequest, request: Request, response: Response,
                  scorer: Annotated[FraudScorer, Depends(get_scorer)]) -> BatchResponse:
    """Up to 256 transactions in one call.

    Defined behaviour for bad items: every item is validated on its own, like a /v1/predict
    body. Valid items are scored; invalid ones come back as status "rejected" with the
    field-level reasons, in the same position. The answer is 200 whenever the batch itself is
    well formed, even if every item is rejected; the batch is refused with 422 only when it is
    not an object holding 1 to 256 items.
    """
    t0 = time.perf_counter()
    results: dict[int, BatchItemResult] = {}
    valid: list[tuple[int, Transaction]] = []
    for index, item in enumerate(body.items):
        try:
            valid.append((index, PredictRequest.model_validate(item).to_domain()))
        except ValidationError as exc:
            results[index] = BatchItemResult(index=index, status="rejected",
                                             details=problems(exc.errors()))
    scores = scorer.score_many([txn for _, txn in valid])
    for (index, _), score in zip(valid, scores, strict=True):
        results[index] = BatchItemResult(index=index, status="scored",
                                         transaction_id=score.transaction_id,
                                         fraud_probability=round(score.probability, 6),
                                         decision=score.decision)
    version = scorer.model.model_version
    log.info("batch_served", items=len(body.items), scored=len(scores),
             rejected=len(body.items) - len(scores),
             decisions=dict(Counter(score.decision.value for score in scores)),
             model_version=version,
             latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    # ABSENT by design, as for single predictions: identifiers, amounts, raw probabilities
    request.app.state.metrics.count_decisions(score.decision.value for score in scores)
    response.headers["X-Model-Version"] = version
    response.headers["Cache-Control"] = "no-store"
    return BatchResponse(
        model_version=version, trace_id=request.state.trace_id,
        summary=BatchSummary(total=len(body.items), scored=len(scores),
                             rejected=len(body.items) - len(scores)),
        results=[results[i] for i in range(len(body.items))],
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
