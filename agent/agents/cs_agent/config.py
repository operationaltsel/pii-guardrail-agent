"""Runtime configuration (12-factor: everything from environment variables)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # local dev convenience; in containers env vars come from the orchestrator
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:  # pragma: no cover
    pass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _opt_float(name: str) -> float | None:
    v = os.getenv(name)
    return float(v) if v else None


@dataclass(frozen=True)
class Settings:
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    # google-genai's own default is 5 attempts with backoff up to 60s between tries — fine for
    # a batch job, bad for a chat UI where the user is staring at a typing indicator. Fewer,
    # faster attempts surface a retryable error quickly so the frontend's own "Coba lagi"
    # button (and the user) can decide, instead of silently blocking for up to a minute.
    gemini_retry_attempts: int = field(default_factory=lambda: int(os.getenv("GEMINI_RETRY_ATTEMPTS", "2")))
    gemini_retry_initial_delay_s: float = field(default_factory=lambda: float(os.getenv("GEMINI_RETRY_INITIAL_DELAY_S", "1.0")))
    gemini_retry_max_delay_s: float = field(default_factory=lambda: float(os.getenv("GEMINI_RETRY_MAX_DELAY_S", "4.0")))
    ner_url: str = field(default_factory=lambda: os.getenv("NER_SERVICE_URL", "http://localhost:8001"))
    ner_timeout_s: float = field(default_factory=lambda: float(os.getenv("NER_TIMEOUT_S", "3.0")))
    ner_threshold: float | None = field(default_factory=lambda: _opt_float("NER_THRESHOLD"))
    ner_api_key: str | None = field(default_factory=lambda: os.getenv("NER_API_KEY") or None)
    # pseudonymize = reversible [REDACT_NAMA_1] tokens (default) | mask = [REDACT_NAMA] as in the brief
    redaction_mode: str = field(default_factory=lambda: os.getenv("PII_REDACTION_MODE", "pseudonymize"))
    # closed = refuse to call the LLM when NER is down (safe default) | open = continue regex-only
    fail_mode: str = field(default_factory=lambda: os.getenv("PII_FAIL_MODE", "closed"))
    # put the user's own PII back into the reply shown to them (LLM never sees it)
    restore_output: bool = field(default_factory=lambda: _bool("PII_RESTORE_OUTPUT", True))


def get_settings() -> Settings:
    return Settings()
