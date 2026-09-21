"""Evaluation metrics for span-based PII detection.

Three complementary views:

* **strict**  — exact (start, end, label) match; the standard NER metric (≈ seqeval entity F1).
* **lenient** — a gold span counts as found if any predicted span with the same label overlaps
  it. Boundary errors like "Jl. Mawar No. 5" vs "Jl. Mawar No. 5 Bandung" are penalised by
  strict but still redact most of the PII.
* **char**    — the guardrail's real objective, label-agnostic:
    - ``leak_rate``: share of gold PII characters NOT covered by any prediction (lower = safer)
    - ``over_redaction``: share of non-PII characters that were redacted (lower = more useful)
    - ``clean_message_rate``: share of messages where no PII character leaked at all
"""
from __future__ import annotations

from collections import defaultdict

Span = tuple[int, int, str]


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": tp, "fp": fp, "fn": fn}


def _fbeta(p: float, r: float, beta: float) -> float:
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r) if (b2 * p + r) else 0.0


def span_metrics(gold: list[list[Span]], pred: list[list[Span]], texts: list[str],
                 labels: tuple[str, ...] = ("PERSON", "ADDRESS")) -> dict:
    gold = [[g for g in gs if g[2] in labels] for gs in gold]
    pred = [[p for p in ps if p[2] in labels] for ps in pred]

    strict = defaultdict(lambda: [0, 0, 0])
    lenient = defaultdict(lambda: [0, 0, 0])
    leaked = pii_total = over = non_pii_total = clean = 0

    for gs, ps, text in zip(gold, pred, texts):
        gset, pset = set(gs), set(ps)
        for lab in labels:
            g_l = {g for g in gset if g[2] == lab}
            p_l = {p for p in pset if p[2] == lab}
            strict[lab][0] += len(g_l & p_l)
            strict[lab][1] += len(p_l - g_l)
            strict[lab][2] += len(g_l - p_l)
            overlap = lambda a, b: a[0] < b[1] and b[0] < a[1]
            lenient[lab][0] += sum(any(overlap(g, p) for p in p_l) for g in g_l)
            lenient[lab][2] += sum(not any(overlap(g, p) for p in p_l) for g in g_l)
            lenient[lab][1] += sum(not any(overlap(p, g) for g in g_l) for p in p_l)

        gold_mask = [False] * len(text)
        pred_mask = [False] * len(text)
        for s, e, _ in gs:
            gold_mask[s:e] = [True] * (e - s)
        for s, e, _ in ps:
            pred_mask[s:e] = [True] * (e - s)
        msg_leak = 0
        for ch, g, p in zip(text, gold_mask, pred_mask):
            if ch.isspace():
                continue
            if g:
                pii_total += 1
                if not p:
                    leaked += 1
                    msg_leak += 1
            else:
                non_pii_total += 1
                over += p
        clean += msg_leak == 0

    per_label = {lab: _prf(*strict[lab]) for lab in labels}
    micro = _prf(*(sum(strict[l][i] for l in labels) for i in range(3)))
    micro["f2"] = round(_fbeta(micro["precision"], micro["recall"], 2.0), 4)
    len_micro = _prf(*(sum(lenient[l][i] for l in labels) for i in range(3)))
    return {
        "per_label": per_label,
        "micro": micro,
        "lenient": {"micro": len_micro, "per_label": {l: _prf(*lenient[l]) for l in labels}},
        "char": {
            "leak_rate": round(leaked / pii_total, 4) if pii_total else 0.0,
            "over_redaction": round(over / non_pii_total, 4) if non_pii_total else 0.0,
            "clean_message_rate": round(clean / len(texts), 4) if texts else 1.0,
            "pii_chars": pii_total,
        },
        "n_messages": len(texts),
    }
