"""ADK lifecycle callbacks that enforce the PII guardrail.

    user msg ──► before_model_callback ──► Gemini ──► after_model_callback ──► user
                 (redact every request)              (restore user's own PII
                                                       in the displayed reply)
    Gemini tool call ──► before_tool_callback ──► tool ──► after_tool_callback ──► Gemini
                         (tokens -> real values,          (tool output PII -> tokens)
                          server-side only)

Invariant: **no raw PII ever reaches the LLM** — not in the user turn, not in history,
not in tool results. Everything that crosses into ``llm_request`` passes through here.

Notes on ADK internals (google-adk 2.9): request contents are *shallow* copies of session
events. Setting ``part.text`` is safe; nested objects (e.g. ``function_response``) must be
replaced, never mutated in place, or the session history would be corrupted.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Optional

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ..config import Settings
from .ner_client import NerClient, NerUnavailable
from .redactor import Redactor
from .vault import Vault

log = logging.getLogger("guardrail")

FAIL_CLOSED_MESSAGE = (
    "Mohon maaf, sistem perlindungan data kami sedang mengalami gangguan sehingga pesan Anda "
    "belum dapat diproses dengan aman. Silakan coba lagi dalam beberapa saat. "
    "Data pribadi Anda tidak dikirim ke mana pun."
)
# Not "temp:"-prefixed on purpose: ADK's session service strips temp: keys from the
# event's own actions.state_delta before it is yielded to callers (base_session_service.py
# _trim_temp_delta_state, called from append_event during runner.run_async) — a client
# streaming /run_sse would never see it. This key holds counts/booleans/latency only
# (never a raw PII value), so persisting it in ordinary session state is safe; a frontend
# uses it purely as live evidence that the guardrail ran on this turn.
REPORT_KEY = "pii_report"


class PiiGuardrail:
    def __init__(self, settings: Settings, ner_client: NerClient | None = None):
        self.s = settings
        self.ner = ner_client or NerClient(settings.ner_url, timeout_s=settings.ner_timeout_s,
                                           threshold=settings.ner_threshold, api_key=settings.ner_api_key)
        self.redactor = Redactor(ner=self.ner)

    # ------------------------------------------------------------ model in
    async def before_model(self, callback_context, llm_request: LlmRequest) -> Optional[LlmResponse]:
        t0 = time.perf_counter()
        vault = Vault.from_state(callback_context.state, self.s.redaction_mode)
        counts: Counter = Counter()
        ner_ms, degraded = None, False

        for content in llm_request.contents or []:
            for part in content.parts or []:
                if part.text and not part.thought:
                    if content.role == "user":
                        try:
                            res = await self.redactor.redact(part.text, vault, use_ner=not degraded)
                        except NerUnavailable as err:
                            if self.s.fail_mode == "closed":
                                log.error("NER unavailable, failing closed: %s", err)
                                callback_context.state[REPORT_KEY] = {"blocked": True, "reason": "ner_unavailable"}
                                return LlmResponse(content=types.Content(
                                    role="model", parts=[types.Part(text=FAIL_CLOSED_MESSAGE)]))
                            log.warning("NER unavailable, degrading to regex-only (fail-open): %s", err)
                            degraded = True
                            res = await self.redactor.redact(part.text, vault, use_ner=False)
                        part.text = res.text
                        counts.update(f.label for f in res.findings)
                        ner_ms = res.ner_ms if res.ner_ms is not None else ner_ms
                    else:  # model-authored text may contain PII restored by after_model
                        part.text = self.redactor.redact_light(part.text, vault)
                elif part.function_response is not None and part.function_response.response:
                    clean = self.redactor.redact_structured(part.function_response.response, vault)
                    part.function_response = part.function_response.model_copy(update={"response": clean})
                elif part.function_call is not None and part.function_call.args:
                    clean = self.redactor.redact_structured(part.function_call.args, vault)
                    part.function_call = part.function_call.model_copy(update={"args": clean})

        vault.save(callback_context.state)
        report = {"blocked": False, "degraded_regex_only": degraded, "detected": dict(counts),
                  "ner_ms": round(ner_ms, 1) if ner_ms is not None else None,
                  "guardrail_ms": round((time.perf_counter() - t0) * 1000, 1),
                  "vault_size": len(vault.tokens)}
        callback_context.state[REPORT_KEY] = report
        log.info("guardrail before_model %s", report)
        return None

    # ----------------------------------------------------------- model out
    async def after_model(self, callback_context, llm_response: LlmResponse) -> Optional[LlmResponse]:
        if not self.s.restore_output or self.s.redaction_mode == "mask":
            return None
        if llm_response.partial or not llm_response.content or not llm_response.content.parts:
            return None  # streaming chunks may split a token; restore on the final response only
        vault = Vault.from_state(callback_context.state, self.s.redaction_mode)
        if not vault.tokens:
            return None
        changed = False
        for part in llm_response.content.parts:
            if part.text and not part.thought:
                restored = vault.detokenize(part.text)
                changed |= restored != part.text
                part.text = restored
        return llm_response if changed else None

    # ------------------------------------------------------------- tools
    async def before_tool(self, tool, args: dict[str, Any], tool_context) -> Optional[dict]:
        """Swap tokens for real values so the tool can do its job. ``args`` is ADK's private
        deep copy for this call, so the LLM-visible history keeps the tokens."""
        vault = Vault.from_state(tool_context.state, self.s.redaction_mode)
        restored = 0
        for k, v in list(args.items()):
            new = vault.detokenize_obj(v)
            restored += new != v
            args[k] = new
        if restored:
            log.info("guardrail: tool %s received %d de-tokenised argument(s)", tool.name, restored)
        return None

    async def after_tool(self, tool, args: dict[str, Any], tool_context, tool_response: dict) -> Optional[dict]:
        vault = Vault.from_state(tool_context.state, self.s.redaction_mode)
        clean = self.redactor.redact_structured(tool_response, vault)
        vault.save(tool_context.state)
        return clean
