"""Annotation helpers shared by the generator, trainers and evaluator.

The canonical data format is JSONL with character-level spans::

    {"text": "Nama saya Budi", "entities": [[10, 14, "PERSON"]]}

Character spans keep the dataset model-agnostic: the transformer aligns them to
sub-word tokens, the CRF aligns them to words, and the evaluator compares spans
directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LABELS = ("PERSON", "ADDRESS")  # what the NER model predicts
REGEX_LABELS = ("NIK", "EMAIL", "PHONE")  # gold-only tags, handled by the regex guardrail
BIO_LABELS = ["O", "B-PERSON", "I-PERSON", "B-ADDRESS", "I-ADDRESS"]

_TAG_RE = re.compile(r"<(PERSON|ADDRESS|NIK|EMAIL|PHONE)>(.*?)</\1>", re.DOTALL)
_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_EDGE_PUNCT = " \t\n,.;:!?"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str

    def as_list(self) -> list:
        return [self.start, self.end, self.label]


def parse_inline(marked: str) -> tuple[str, list[Span]]:
    """Convert ``Nama saya <PERSON>Budi</PERSON>`` into text + spans."""
    out, spans, cursor, pos = [], [], 0, 0
    for m in _TAG_RE.finditer(marked):
        out.append(marked[cursor:m.start()])
        pos += m.start() - cursor
        inner = m.group(2)
        spans.append(Span(pos, pos + len(inner), m.group(1)))
        out.append(inner)
        pos += len(inner)
        cursor = m.end()
    out.append(marked[cursor:])
    text = "".join(out)
    if re.search(r"</?(PERSON|ADDRESS|NIK|EMAIL|PHONE)>", text):
        raise ValueError(f"Unbalanced tag in: {marked!r}")
    return text, [normalize_span(text, s) for s in spans]


def to_inline(text: str, spans: Iterable[Span]) -> str:
    parts, cursor = [], 0
    for s in sorted(spans, key=lambda s: s.start):
        parts += [text[cursor:s.start], f"<{s.label}>", text[s.start:s.end], f"</{s.label}>"]
        cursor = s.end
    parts.append(text[cursor:])
    return "".join(parts)


def normalize_span(text: str, span: Span) -> Span:
    """Strip whitespace / trailing punctuation at the edges (guideline rule)."""
    start, end = span.start, span.end
    while start < end and text[start] in _EDGE_PUNCT:
        start += 1
    while end > start and text[end - 1] in _EDGE_PUNCT:
        # keep the dot of an abbreviation like "Jl." / "No." only when it is not the edge
        end -= 1
    return Span(start, end, span.label)


def tokenize_words(text: str) -> list[tuple[str, int, int]]:
    """Word-level tokenization with character offsets (used by CRF & evaluation)."""
    return [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def spans_to_bio(words: list[tuple[str, int, int]], spans: Iterable[Span]) -> list[str]:
    tags = ["O"] * len(words)
    for s in spans:
        first = True
        for i, (_, ws, we) in enumerate(words):
            if ws >= s.start and we <= s.end:
                tags[i] = ("B-" if first else "I-") + s.label
                first = False
    return tags


def bio_to_spans(words: list[tuple[str, int, int]], tags: list[str], text: str) -> list[Span]:
    """Lenient BIO decoding: an orphan ``I-X`` opens a new entity."""
    spans, cur_label, cur_start, cur_end = [], None, 0, 0
    for (_, ws, we), tag in zip(words, tags):
        if tag == "O":
            if cur_label:
                spans.append(Span(cur_start, cur_end, cur_label))
            cur_label = None
            continue
        prefix, label = tag.split("-", 1)
        if prefix == "B" or label != cur_label:
            if cur_label:
                spans.append(Span(cur_start, cur_end, cur_label))
            cur_label, cur_start = label, ws
        cur_end = we
    if cur_label:
        spans.append(Span(cur_start, cur_end, cur_label))
    return [normalize_span(text, s) for s in spans if s.end > s.start]


def load_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_jsonl(rows: Iterable[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def row_spans(row: dict) -> list[Span]:
    return [Span(s, e, l) for s, e, l in row["entities"]]


def load_gold(path: str | Path) -> list[dict]:
    """Load the hand-written gold file (inline tags, ``# category:`` headers)."""
    rows, category = [], "general"
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# category:"):
            category = line.split(":", 1)[1].strip()
            continue
        if line.startswith("#"):
            continue
        # literal "\n" in the gold file represents a newline inside one chat message
        text, spans = parse_inline(line.replace("\\n", "\n"))
        rows.append({"text": text, "entities": [s.as_list() for s in spans], "category": category})
    return rows
