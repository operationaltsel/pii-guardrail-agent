"""NER inference engine: tokenizer + model (ONNX Runtime or PyTorch) + span decoding.

This module is the single source of truth for turning text into entities. The training
repo's evaluator imports it directly, so the metrics we report are measured on exactly
the code path that runs in production ("evaluate what you ship").

Decoding strategy
-----------------
1. Sliding-window tokenisation (``max_length``/``stride``) so long messages are never
   silently truncated — a truncated tail would be an unguarded PII leak. Windows are kept
   short (96 tokens, 32 overlap): that matches the length distribution seen in training and
   was measurably more robust on long, repetitive messages than 256-token windows.
2. Sub-word probabilities are averaged per *word* so a word is never half-redacted.
3. A word is an entity when ``1 - P(O) >= threshold``. Lowering the threshold trades
   precision for recall; the default is tuned on the dev split (see model_card.json).
4. Consecutive entity words of the same type form one span; ADDRESS spans separated only
   by punctuation (``,`` ``-`` ``/``) are merged because addresses are contiguous.
5. Existing ``[REDACT_*]`` placeholders are never re-labelled.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

PLACEHOLDER_RE = re.compile(r"\[REDACT_[A-Z]+(?:_\d+)?\]")
_ADDRESS_GAP_RE = re.compile(r"^[\s,.\-/|]*$")
_EDGE = " \t\n,.;:!?|-/"


@dataclass
class Entity:
    text: str
    label: str
    start: int
    end: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class NerEngine:
    def __init__(self, model_dir: str | Path, backend: str | None = None, threads: int | None = None,
                 max_length: int = 96, stride: int = 32, batch_size: int = 16):
        self.model_dir = Path(model_dir)
        meta = json.loads((self.model_dir / "labels.json").read_text(encoding="utf-8"))
        self.labels: list[str] = meta["labels"]
        card_path = self.model_dir / "model_card.json"
        self.card: dict = json.loads(card_path.read_text(encoding="utf-8")) if card_path.exists() else {}
        self.default_threshold: float = float(self.card.get("threshold", 0.5))
        self.batch_size = batch_size

        self.tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self.tokenizer.no_padding()
        # Windowing is done by hand (see _windows): tokenizers 0.23's `overflowing` only yields a
        # tiny tail window, which silently truncated long messages (caught by test_api.py).
        self.tokenizer.no_truncation()
        self.max_length, self.stride = max_length, stride
        self.pad_id = self.tokenizer.token_to_id("[PAD]") or 0
        self.cls_id = self.tokenizer.token_to_id("[CLS]")
        self.sep_id = self.tokenizer.token_to_id("[SEP]")

        onnx_path = self.model_dir / "model.onnx"
        self.backend = backend or ("onnx" if onnx_path.exists() else "torch")
        threads = threads or int(os.getenv("NER_THREADS", "0")) or None
        if self.backend == "onnx":
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            if threads:
                opts.intra_op_num_threads = threads
            self.session = ort.InferenceSession(str(onnx_path), opts, providers=["CPUExecutionProvider"])
            self.input_names = {i.name for i in self.session.get_inputs()}
        else:
            import torch
            from transformers import AutoModelForTokenClassification

            if threads:
                torch.set_num_threads(threads)
            self.torch = torch
            self.model = AutoModelForTokenClassification.from_pretrained(self.model_dir).eval()

        # label index groups
        self.o_idx = self.labels.index("O")
        self.types = sorted({l.split("-", 1)[1] for l in self.labels if l != "O"})
        self.type_idx = {t: [i for i, l in enumerate(self.labels) if l.endswith("-" + t)] for t in self.types}

    # ------------------------------------------------------------------ model
    def _forward(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        feeds = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        if self.backend == "onnx":
            feeds = {k: v for k, v in feeds.items() if k in self.input_names}
            return self.session.run(None, feeds)[0]
        with self.torch.inference_mode():
            t = {k: self.torch.from_numpy(v) for k, v in feeds.items()}
            return self.model(**t).logits.numpy()

    def _probs_for(self, id_lists: list[list[int]]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for i in range(0, len(id_lists), self.batch_size):
            chunk = id_lists[i:i + self.batch_size]
            width = max(len(x) for x in chunk)
            ids = np.full((len(chunk), width), self.pad_id, dtype=np.int64)
            mask = np.zeros((len(chunk), width), dtype=np.int64)
            for j, x in enumerate(chunk):
                ids[j, :len(x)] = x
                mask[j, :len(x)] = 1
            probs = _softmax(self._forward(ids, mask).astype(np.float32))
            out += [probs[j, :len(x)] for j, x in enumerate(chunk)]
        return out

    def _windows(self, enc) -> list[list[int]]:
        """Split content-token positions into overlapping windows of max_length-2 (+CLS/SEP)."""
        content = [i for i, (w, (s, t)) in enumerate(zip(enc.word_ids, enc.offsets)) if w is not None and s != t]
        size, step = self.max_length - 2, self.max_length - 2 - self.stride
        windows, start = [], 0
        while True:
            windows.append(content[start:start + size])
            if start + size >= len(content):
                return windows
            start += step

    # --------------------------------------------------------------- decoding
    def predict_batch(self, texts: list[str], threshold: float | None = None) -> list[list[Entity]]:
        thr = self.default_threshold if threshold is None else threshold
        encs = [self.tokenizer.encode(t) for t in texts]
        id_lists, owner = [], []  # owner: (text index, token positions of this window)
        for ti, enc in enumerate(encs):
            for positions in self._windows(enc):
                id_lists.append([self.cls_id] + [enc.ids[p] for p in positions] + [self.sep_id])
                owner.append((ti, positions))
        probs = self._probs_for(id_lists) if id_lists else []

        # word_id -> [start, end, prob_sum, n]; windows overlap, so average across them
        words: list[dict[int, list]] = [dict() for _ in texts]
        for p, (ti, positions) in zip(probs, owner):
            enc = encs[ti]
            for k, pos in enumerate(positions, start=1):  # k=0 is [CLS]
                s, t = enc.offsets[pos]
                w = words[ti].setdefault(enc.word_ids[pos], [s, t, np.zeros(len(self.labels)), 0])
                w[0], w[1] = min(w[0], s), max(w[1], t)
                w[2] += p[k]
                w[3] += 1
        return [self._decode(texts[i], words[i], thr) for i in range(len(texts))]

    def predict(self, text: str, threshold: float | None = None) -> list[Entity]:
        return self.predict_batch([text], threshold)[0]

    def _decode(self, text: str, words: dict[int, list], thr: float) -> list[Entity]:
        blocked = [(m.start(), m.end()) for m in PLACEHOLDER_RE.finditer(text)]
        spans: list[list] = []  # [start, end, type, [scores]]
        prev_type = None
        for wid in sorted(words, key=lambda k: words[k][0]):
            s, t, psum, n = words[wid]
            p = psum / n
            if any(bs <= s < be for bs, be in blocked) or 1.0 - p[self.o_idx] < thr:
                prev_type = None
                continue
            mass = {ty: float(p[idx].sum()) for ty, idx in self.type_idx.items()}
            ty = max(mass, key=mass.get)
            if prev_type == ty and spans:
                spans[-1][1] = t
                spans[-1][3].append(mass[ty])
            else:
                spans.append([s, t, ty, [mass[ty]]])
            prev_type = ty

        merged: list[list] = []
        for sp in spans:
            if merged and merged[-1][2] == sp[2] == "ADDRESS" and _ADDRESS_GAP_RE.match(text[merged[-1][1]:sp[0]]):
                merged[-1][1] = sp[1]
                merged[-1][3] += sp[3]
            else:
                merged.append(sp)

        entities = []
        for s, t, ty, scores in merged:
            while s < t and text[s] in _EDGE:
                s += 1
            while t > s and text[t - 1] in _EDGE:
                t -= 1
            if t > s:
                entities.append(Entity(text[s:t], ty, s, t, round(float(np.mean(scores)), 4)))
        return entities

    def info(self) -> dict:
        return {"backend": self.backend, "labels": self.labels, "threshold": self.default_threshold,
                **{k: v for k, v in self.card.items() if k not in ("threshold",)}}
