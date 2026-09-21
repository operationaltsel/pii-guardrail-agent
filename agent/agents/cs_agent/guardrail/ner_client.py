"""HTTP client for the NER microservice, with timeout, retry and a circuit breaker.

The agent treats NER as a remote dependency that *will* fail sometimes (pod restart,
network blip, overload). The client makes those failures explicit so the guardrail can
decide what to do (fail-closed by default — see callbacks.py) instead of hanging the chat.

* timeout         — a guardrail must not add unbounded latency to every turn
* retry           — one quick retry absorbs transient connection resets
* circuit breaker — after N consecutive failures, stop calling for ``cooldown`` seconds so a
                    dead service doesn't cost ``timeout`` on every message
* LRU cache       — conversation history is re-sent to the LLM every turn; caching avoids
                    re-running NER on messages that were already analysed
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict

import httpx

from .types import PiiSpan

log = logging.getLogger("guardrail.ner_client")


class NerUnavailable(RuntimeError):
    pass


class NerClient:
    def __init__(self, base_url: str, timeout_s: float = 3.0, retries: int = 1, threshold: float | None = None,
                 failure_threshold: int = 3, cooldown_s: float = 30.0, cache_size: int = 512,
                 api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.retries = retries
        self.threshold = threshold
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self._failures = 0
        self._open_until = 0.0
        self._cache: OrderedDict[str, list[PiiSpan]] = OrderedDict()
        self._cache_size = cache_size
        self._client: httpx.AsyncClient | None = None
        self._client_loop = None
        self.last_latency_ms: float | None = None

    def _http(self) -> httpx.AsyncClient:
        # an AsyncClient is bound to the event loop it was created on (keep-alive pool)
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, headers=self.headers)
            self._client_loop = loop
        return self._client

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    async def detect(self, text: str) -> list[PiiSpan]:
        if not text.strip():
            return []
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            self.last_latency_ms = 0.0
            return self._cache[key]
        if self.circuit_open:
            raise NerUnavailable("circuit open: NER service recently failing")

        payload = {"text": text}
        if self.threshold is not None:
            payload["threshold"] = self.threshold
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._http().post(f"{self.base_url}/v1/ner", json=payload)
                resp.raise_for_status()
                data = resp.json()
                self.last_latency_ms = (time.perf_counter() - t0) * 1000
                spans = [PiiSpan(e["start"], e["end"], e["label"], e["text"], "ner", e.get("score", 1.0))
                         for e in data["entities"]]
                self._failures = 0
                self._cache[key] = spans
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
                return spans
            except (httpx.HTTPError, KeyError, ValueError) as err:
                last_err = err
                if isinstance(err, httpx.HTTPStatusError) and err.response.status_code < 500:
                    break  # 4xx will not fix itself on retry
                if attempt < self.retries:
                    await asyncio.sleep(0.15 * (attempt + 1))
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.monotonic() + self.cooldown_s
            log.error("NER circuit opened for %.0fs after %d failures", self.cooldown_s, self._failures)
        raise NerUnavailable(f"NER service call failed: {type(last_err).__name__}: {last_err}")

    async def health(self) -> bool:
        try:
            r = await self._http().get(f"{self.base_url}/health/ready")
            return r.status_code == 200
        except httpx.HTTPError:
            return False
