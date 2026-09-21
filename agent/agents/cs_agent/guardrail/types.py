from __future__ import annotations

from dataclasses import asdict, dataclass

# Placeholder tag per PII label. NAMA/ADDRESS follow the format in the assignment brief.
TAGS = {"PERSON": "NAMA", "ADDRESS": "ADDRESS", "NIK": "NIK", "EMAIL": "EMAIL", "PHONE": "PHONE"}
LABEL_OF_TAG = {v: k for k, v in TAGS.items()}


@dataclass(frozen=True)
class PiiSpan:
    start: int
    end: int
    label: str          # PERSON | ADDRESS | NIK | EMAIL | PHONE
    text: str
    source: str         # "regex" | "ner" | "vault" | "field"
    score: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)
