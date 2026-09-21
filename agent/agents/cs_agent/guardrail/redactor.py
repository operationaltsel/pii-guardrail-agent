"""Redaction pipeline: vault (known PII) -> regex (structured PII) -> NER (names & addresses).

Order matters:
1. **Vault first** — PII seen in earlier turns (or restored into the agent's own replies) is
   re-tokenised consistently, and never re-sent to the NER service.
2. **Regex second** — cheap, deterministic, near-100% recall for NIK/email/phone.
3. **NER last, on the regex-redacted text** — data minimisation: the NER service never
   receives NIK/email/phone at all, only what regex could not handle.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .ner_client import NerClient
from .regex_detector import RegexDetector
from .types import PiiSpan
from .vault import TOKEN_RE, Vault

NER_LABELS = ("PERSON", "ADDRESS")

# Structured tool outputs: PII is declared by field name, not guessed from 2-word strings
# (NER needs sentence context and would be unreliable on a bare "Budi Santoso").
FIELD_POLICY: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|_)(nik|ktp)($|_)"), "NIK"),
    (re.compile(r"email"), "EMAIL"),
    (re.compile(r"(telepon|telp|phone|(^|_)hp($|_)|(^|_)wa($|_)|kontak|contact)"), "PHONE"),
    (re.compile(r"(alamat|address)"), "ADDRESS"),
    (re.compile(r"(^|_)(nama|name|pelapor|penerima|pemilik|pic)($|_)"), "PERSON"),
]


def field_label(key: str | None) -> str | None:
    if not key:
        return None
    k = key.lower()
    for rx, label in FIELD_POLICY:
        if rx.search(k):
            return label
    return None


@dataclass
class RedactionResult:
    text: str
    findings: list[PiiSpan] = field(default_factory=list)
    regex_ms: float = 0.0
    ner_ms: float | None = None


def apply_spans(text: str, spans: list[PiiSpan], vault: Vault) -> str:
    for s in sorted(spans, key=lambda s: s.start, reverse=True):
        if TOKEN_RE.fullmatch(text[s.start:s.end]):
            continue
        text = text[:s.start] + vault.tokenize(s.label, text[s.start:s.end]) + text[s.end:]
    return text


class Redactor:
    def __init__(self, regex: RegexDetector | None = None, ner: NerClient | None = None):
        self.regex = regex or RegexDetector()
        self.ner = ner

    async def redact(self, text: str, vault: Vault, use_ner: bool = True) -> RedactionResult:
        """Raises NerUnavailable if NER is required but the service is down."""
        t = vault.replace_known(text)
        t0 = time.perf_counter()
        regex_spans = self.regex.detect(t)
        t = apply_spans(t, regex_spans, vault)
        res = RedactionResult(t, list(regex_spans), regex_ms=(time.perf_counter() - t0) * 1000)
        if use_ner and self.ner is not None and TOKEN_RE.sub("", t).strip():
            ner_spans = [s for s in await self.ner.detect(t) if s.label in NER_LABELS]
            res.ner_ms = self.ner.last_latency_ms
            res.text = apply_spans(t, ner_spans, vault)
            res.findings += ner_spans
        return res

    def redact_light(self, text: str, vault: Vault) -> str:
        """Vault + regex only (no network). Used for model-authored text and tool payloads."""
        t = vault.replace_known(text)
        return apply_spans(t, self.regex.detect(t), vault)

    def redact_structured(self, obj: Any, vault: Vault, key: str | None = None) -> Any:
        """Sanitise a tool response: field-name policy for declared PII, regex for the rest."""
        if isinstance(obj, dict):
            return {k: self.redact_structured(v, vault, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact_structured(v, vault, key) for v in obj]
        if isinstance(obj, str) and obj.strip():
            label = field_label(key)
            if label and not TOKEN_RE.fullmatch(obj.strip()):
                if label == "PHONE":  # "kontak" may hold an email instead
                    found = self.regex.detect(obj)
                    label = found[0].label if found else label
                return vault.tokenize(label, obj.strip())
            return self.redact_light(obj, vault)
        return obj
