"""NER microservice (FastAPI + ONNX Runtime).

Endpoints
    POST /v1/ner          text -> entities (PERSON, ADDRESS) with char offsets
    POST /v1/ner/batch    up to 64 texts
    GET  /v1/model        model card: version, labels, threshold, metrics
    GET  /health/live     liveness  (process up)
    GET  /health/ready    readiness (model loaded + warm-up inference succeeded)
    GET  /metrics         Prometheus metrics (request count, latency histogram)

Privacy: request text is **never logged**; only sizes, counts and latencies are.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .inference import NerEngine
from .schemas import EntityOut, NerBatchRequest, NerBatchResponse, NerRequest, NerResponse

log = logging.getLogger("ner_service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MODEL_DIR = Path(os.getenv("NER_MODEL_DIR", Path(__file__).resolve().parents[1] / "model"))
API_KEY = os.getenv("NER_API_KEY") or None

REQS = Counter("ner_requests_total", "NER requests", ["endpoint", "status"])
LAT = Histogram("ner_inference_seconds", "Model inference latency",
                buckets=(0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.5))
ENTS = Counter("ner_entities_total", "Entities returned", ["label"])

state: dict = {"engine": None, "ready": False}


@asynccontextmanager
async def lifespan(_: FastAPI):
    t0 = time.perf_counter()
    engine = NerEngine(MODEL_DIR)
    engine.predict("Nama saya Budi, tinggal di Jl. Mawar No. 1")  # warm-up: first ORT run is slow
    state.update(engine=engine, ready=True)
    log.info("model loaded from %s (backend=%s) in %.2fs", MODEL_DIR, engine.backend, time.perf_counter() - t0)
    yield
    state.update(engine=None, ready=False)


app = FastAPI(title="PII NER Service", version="1.0.0", lifespan=lifespan,
              description="Named Entity Recognition for Indonesian PII (PERSON, ADDRESS).")


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


def _engine() -> NerEngine:
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="model not loaded")
    return state["engine"]


def _version(engine: NerEngine) -> str:
    return engine.card.get("model_version", "dev")


@app.post("/v1/ner", response_model=NerResponse, dependencies=[Depends(require_key)])
def ner(req: NerRequest) -> NerResponse:
    # sync endpoint -> runs in FastAPI's threadpool; ORT sessions are thread-safe
    engine = _engine()
    t0 = time.perf_counter()
    ents = engine.predict(req.text, req.threshold)
    dt = time.perf_counter() - t0
    LAT.observe(dt)
    REQS.labels("ner", "ok").inc()
    for e in ents:
        ENTS.labels(e.label).inc()
    log.info("ner chars=%d entities=%d ms=%.1f", len(req.text), len(ents), dt * 1000)
    return NerResponse(entities=[EntityOut(**e.to_dict()) for e in ents], model_version=_version(engine),
                       inference_ms=round(dt * 1000, 2))


@app.post("/v1/ner/batch", response_model=NerBatchResponse, dependencies=[Depends(require_key)])
def ner_batch(req: NerBatchRequest) -> NerBatchResponse:
    engine = _engine()
    t0 = time.perf_counter()
    results = engine.predict_batch(req.texts, req.threshold)
    dt = time.perf_counter() - t0
    LAT.observe(dt)
    REQS.labels("batch", "ok").inc()
    return NerBatchResponse(results=[[EntityOut(**e.to_dict()) for e in r] for r in results],
                            model_version=_version(engine), inference_ms=round(dt * 1000, 2))


@app.get("/v1/model")
def model_info() -> dict:
    return _engine().info()


@app.get("/health/live")
def live() -> dict:
    return {"status": "alive"}


@app.get("/health/ready")
def ready() -> dict:
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):  # never echo request content in errors
    REQS.labels("any", "error").inc()
    log.exception("unhandled error: %s", type(exc).__name__)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "internal error"})
