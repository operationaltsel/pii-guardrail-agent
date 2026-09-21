"""Session-scoped PII vault for reversible pseudonymisation.

    "Nama saya Budi"  --tokenize-->  "Nama saya [REDACT_NAMA_1]"   (what the LLM sees)
    vault: {"[REDACT_NAMA_1]": "Budi"}                              (stays server-side)

Why not plain masking (``[REDACT_NAMA]``)? A support agent must *act* on the data: create a
ticket with the customer's phone, update an address. With numbered tokens the LLM can pass
``[REDACT_PHONE_1]`` to a tool, and ``before_tool_callback`` swaps the real value back in —
the LLM never sees it, but the tool still works. Same value -> same token, so the model can
also reason ("the number you gave earlier").

``PII_REDACTION_MODE=mask`` switches to the exact format of the brief (``[REDACT_NAMA]``),
which is irreversible.

The vault is JSON-serialisable so it can live in ADK session state. Production note: session
state is persisted by the session service; for a real deployment, encrypt the vault or keep
it in a dedicated store with a TTL (see docs/guardrail.md).
"""
from __future__ import annotations

import re
from typing import Any

from .types import LABEL_OF_TAG, TAGS

TOKEN_RE = re.compile(r"\[REDACT_([A-Z]+)(?:_(\d+))?\]")
STATE_KEY = "pii_vault"


def _norm(label: str, value: str) -> str:
    if label in ("NIK", "PHONE"):
        d = re.sub(r"\D", "", value)
        return "0" + d[2:] if label == "PHONE" and d.startswith("62") else d
    return re.sub(r"\s+", " ", value).strip().casefold()


class Vault:
    def __init__(self, data: dict | None = None, mode: str = "pseudonymize"):
        data = data or {}
        self.tokens: dict[str, dict[str, str]] = dict(data.get("tokens", {}))  # token -> {label, value}
        self.index: dict[str, str] = dict(data.get("index", {}))              # label|norm -> token
        self.counters: dict[str, int] = dict(data.get("counters", {}))
        self.mode = mode
        self.dirty = False

    # ---------------------------------------------------------------- state
    @classmethod
    def from_state(cls, state: Any, mode: str) -> "Vault":
        return cls(state.get(STATE_KEY) if state is not None else None, mode)

    def save(self, state: Any) -> None:
        if self.dirty and state is not None:
            state[STATE_KEY] = self.to_dict()  # assignment -> recorded as a state delta by ADK
            self.dirty = False

    def to_dict(self) -> dict:
        return {"tokens": self.tokens, "index": self.index, "counters": self.counters}

    # ------------------------------------------------------------- tokenize
    def tokenize(self, label: str, value: str) -> str:
        tag = TAGS[label]
        if self.mode == "mask":
            return f"[REDACT_{tag}]"
        key = f"{label}|{_norm(label, value)}"
        if key in self.index:
            return self.index[key]
        n = self.counters.get(tag, 0) + 1
        self.counters[tag] = n
        token = f"[REDACT_{tag}_{n}]"
        self.tokens[token] = {"label": label, "value": value}
        self.index[key] = token
        self.dirty = True
        return token

    def known_values(self) -> list[tuple[str, str]]:
        """(value, token) pairs, longest value first, for re-tokenising earlier PII."""
        pairs = [(v["value"], t) for t, v in self.tokens.items()]
        return sorted(pairs, key=lambda p: -len(p[0]))

    def replace_known(self, text: str) -> str:
        """Replace PII values already in the vault (e.g. restored into a previous model reply)."""
        for value, token in self.known_values():
            if len(value) >= 2 and value.casefold() in text.casefold():
                # word boundaries: vault value "Budi" must not eat into "Budiman"
                text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", token, text, flags=re.IGNORECASE)
        return text

    # ----------------------------------------------------------- detokenize
    def detokenize(self, text: str) -> str:
        def sub(m: re.Match) -> str:
            entry = self.tokens.get(m.group(0))
            return entry["value"] if entry else m.group(0)
        return TOKEN_RE.sub(sub, text)

    def detokenize_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.detokenize(obj)
        if isinstance(obj, dict):
            return {k: self.detokenize_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.detokenize_obj(v) for v in obj]
        return obj

    @staticmethod
    def label_of(token: str) -> str | None:
        m = TOKEN_RE.fullmatch(token)
        return LABEL_OF_TAG.get(m.group(1)) if m else None
