FROM python:3.12-slim
LABEL org.opencontainers.image.title="ventra-cs-agent" \
      org.opencontainers.image.description="Google ADK customer-support agent with PII guardrail (regex + remote NER)"

RUN groupadd -r app && useradd -r -g app app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents ./agents

ENV PYTHONUNBUFFERED=1 PORT=8000 ALLOW_ORIGINS=http://localhost:3100
USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/list-apps', timeout=2)" || exit 1

# `adk api_server` exposes the same agent over HTTP for the web UI / integration; swap for
# `adk web` in local dev (see README) if you want ADK's own built-in developer console
# instead of frontend/. --allow_origins enables CORS for the browser-based frontend
# (see api_server's own docstring: "unauthenticated... trusted network only").
CMD ["sh", "-c", "adk api_server agents --host 0.0.0.0 --port ${PORT} --allow_origins ${ALLOW_ORIGINS}"]
