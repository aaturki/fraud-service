"""Composition root and HTTP plumbing: tracing, response headers, one error envelope."""
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fraud_service.adapters.sklearn_model import SklearnModel
from fraud_service.api.metrics import CONTENT_TYPE as METRICS_CONTENT_TYPE
from fraud_service.api.metrics import Metrics
from fraud_service.api.routes import router
from fraud_service.api.schemas import problems
from fraud_service.config import Settings
from fraud_service.domain.entities import Channel, FeatureVector, Transaction
from fraud_service.logging_setup import configure_logging, get_logger
from fraud_service.service.scorer import FraudScorer

log = get_logger(__name__)

# A caller's trace id is echoed in a header and written to every log line, so it is accepted
# only when it is short and plain. Anything else is replaced, never trusted.
TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
# Far above one transaction (about 250 bytes) and above a full 256-item batch.
MAX_BODY_BYTES = 256 * 1024
ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE",
               503: "MODEL_UNAVAILABLE"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Composition root: the one place concrete classes meet.
    The model loads HERE: visible, timed, failable."""
    settings = Settings()                 # invalid config? crash here, with field names
    configure_logging(settings.log_level)
    # The config-drift guard: one line showing what this process REALLY runs with.
    log.info("settings_effective",
             **settings.model_dump(mode="json", exclude={"registry_token"}))
    app.state.settings = settings
    app.state.started_at = datetime.now(UTC)

    t0 = time.perf_counter()
    model = SklearnModel.load(settings.model_path)     # fail fast if absent
    model.predict_proba(_warmup_features())            # pay first-call cost now
    app.state.scorer = FraudScorer(model=model, block_threshold=settings.block_threshold)
    app.state.model_version = model.model_version      # stamped on every response
    log.info("model_loaded", version=model.model_version,
             seconds=round(time.perf_counter() - t0, 3))
    yield
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(title="Raqib fraud-scoring service", version="1.1.0", lifespan=lifespan,
                  description="Scores one card transaction for fraud risk and answers "
                              "allow, review or block. SDA-AIE-113, SDAIA Academy.")
    app.include_router(router, prefix="/v1")
    app.state.metrics = Metrics()

    @app.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
    def metrics(request: Request) -> PlainTextResponse:
        """Prometheus scrape target: request counter, latency histogram, decisions, model."""
        text = request.app.state.metrics.render(getattr(request.app.state, "model_version", None))
        return PlainTextResponse(text, media_type=METRICS_CONTENT_TYPE,
                                 headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def trace_and_log(request: Request,
                            call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        trace_id = _incoming_trace_id(request)
        request.state.trace_id = trace_id
        structlog.contextvars.clear_contextvars()
        # On every log line of this request: which request, and which model answered it.
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            model_version=getattr(request.app.state, "model_version", None) or "not-loaded")
        t0 = time.perf_counter()
        if _declared_length(request) > MAX_BODY_BYTES:
            response: Response = _error(request, 413, "PAYLOAD_TOO_LARGE",
                                        f"Request body is larger than {MAX_BODY_BYTES} bytes")
        else:
            try:
                response = await call_next(request)
            except Exception:
                # The 500 is built outside this middleware; log the request line here so
                # the failed requests are not the ones missing from the log.
                log.warning("http_request", method=request.method, path=request.url.path,
                            status=500, latency_ms=_ms_since(t0))
                _observe(request, 500, t0)
                raise
        latency_ms = _ms_since(t0)
        _stamp(request, response)
        response.headers["X-Response-Time-Ms"] = str(latency_ms)
        log.info("http_request", method=request.method, path=request.url.path,
                 status=response.status_code, latency_ms=latency_ms)
        _observe(request, response.status_code, t0)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field names and problems only: never echo the offending values back.
        details = [d.model_dump() for d in problems(exc.errors(), prefix_parts=1, root="body")]
        log.warning("validation_rejected", fields=sorted({d["field"] for d in details}))
        return _error(request, 422, "INVALID_REQUEST", "Request body failed validation",
                      details=details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        return _error(request, exc.status_code, code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak stack traces to clients; always give them a trace_id.
        log.error("unhandled_exception", exc_info=exc)
        return _error(request, 500, "INTERNAL_ERROR",
                      "Unexpected error; contact support with trace_id")

    return app


def _incoming_trace_id(request: Request) -> str:
    candidate = request.headers.get("X-Trace-Id", "")
    if TRACE_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex[:16]


def _declared_length(request: Request) -> int:
    value = request.headers.get("content-length", "")
    return int(value) if value.isdigit() else 0


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _route_label(request: Request) -> str:
    """A bounded label: the matched route, or "unmatched" for anything that matched none."""
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    if getattr(route, "param_convertors", None):
        return str(route.path)        # keep the template: ids must never become label values
    return str(request.scope["path"])   # no path parameters: the path is the template


def _observe(request: Request, status: int, t0: float) -> None:
    """Metrics by route; scrapes of /metrics do not count themselves."""
    route = _route_label(request)
    if route != "/metrics":
        request.app.state.metrics.observe_request(request.method, route, status,
                                                  time.perf_counter() - t0)


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "unknown")


def _stamp(request: Request, response: Response) -> None:
    """Every response says which request it answers and which model is serving."""
    response.headers["X-Trace-Id"] = _trace_id(request)
    version = getattr(request.app.state, "model_version", None)
    if version and "X-Model-Version" not in response.headers:
        response.headers["X-Model-Version"] = version


def _error(request: Request, status: int, code: str, message: str,
           headers: Mapping[str, str] | None = None, **extra: object) -> JSONResponse:
    """One error shape for every failure: {"error": {code, message, trace_id}}."""
    body = {"code": code, "message": message, "trace_id": _trace_id(request), **extra}
    response = JSONResponse(status_code=status, content={"error": body}, headers=headers)
    _stamp(request, response)        # 500s are built outside the middleware: stamp here too
    return response


def _warmup_features() -> FeatureVector:
    return Transaction(
        transaction_id="WARMUP-0000", amount_sar=100.0, channel=Channel.POS,
        merchant_category="GROCERY", customer_id="warmup",
        timestamp=datetime.now(UTC)).to_features()
