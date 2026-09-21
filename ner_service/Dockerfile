# Multi-stage build: install deps in a build layer, copy only what's needed to run.
# Runtime image has no compiler, no torch, no training code — just ONNX Runtime + FastAPI.
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
LABEL org.opencontainers.image.title="pii-ner-service" \
      org.opencontainers.image.description="Indonesian PERSON/ADDRESS NER microservice for the CS agent PII guardrail"

RUN groupadd -r app && useradd -r -g app app
WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app
COPY model ./model

ENV PYTHONUNBUFFERED=1 \
    NER_MODEL_DIR=/app/model \
    OMP_NUM_THREADS=2 \
    NER_THREADS=2 \
    PORT=8001

USER app
EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8001/health/ready', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
