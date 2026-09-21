"""Evaluate an NER model on the dev split and the hand-written gold test set.

Usage:
    python evaluate.py --model ../models/crf --kind crf --name crf
    python evaluate.py --model ../../ner_service/model --name indobert-base-onnx-int8
    python evaluate.py --model ../models/indobert-base --backend torch --name indobert-base-torch

Writes ``../reports/<name>.json`` (all metrics) and ``../reports/<name>_errors.md``
(every false negative / false positive on the gold set, for error analysis).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ner_service"))

from annotation import LABELS, load_gold, load_jsonl, to_inline, Span  # noqa: E402
from metrics import span_metrics  # noqa: E402

DATA = ROOT / "ner_training" / "data"
REPORTS = ROOT / "ner_training" / "reports"


def load_model(path: str, kind: str, backend: str | None, threads: int | None):
    if kind == "crf":
        from train_crf import CrfPredictor
        return CrfPredictor(path)
    from app.inference import NerEngine
    return NerEngine(path, backend=backend, threads=threads)


def run(model, rows: list[dict], threshold: float | None) -> tuple[list[list[tuple]], list[float]]:
    preds, lat = [], []
    model.predict_batch([rows[0]["text"]], threshold)  # warm-up
    for r in rows:  # one message at a time == the production call pattern
        t0 = time.perf_counter()
        ents = model.predict_batch([r["text"]], threshold)[0]
        lat.append((time.perf_counter() - t0) * 1000)
        preds.append([(e.start, e.end, e.label) for e in ents])
    return preds, lat


def evaluate_rows(rows, preds) -> dict:
    gold = [[tuple(e) for e in r["entities"]] for r in rows]
    return span_metrics(gold, preds, [r["text"] for r in rows], LABELS)


def error_report(rows, preds, name: str) -> str:
    lines = [f"# Error analysis — `{name}` on gold test set\n",
             "Format: **gold** vs **pred** (tag inline). Hanya kalimat yang mengandung kesalahan.\n"]
    n_err = 0
    for r, p in zip(rows, preds):
        g = {tuple(e) for e in r["entities"] if e[2] in LABELS}
        ps = set(p)
        if g == ps:
            continue
        n_err += 1
        fn = sorted(g - ps)
        fp = sorted(ps - g)
        lines.append(f"### [{r['category']}] #{n_err}")
        lines.append("- gold: `" + to_inline(r["text"], [Span(*x) for x in sorted(g)]).replace("\n", "\\n") + "`")
        lines.append("- pred: `" + to_inline(r["text"], [Span(*x) for x in sorted(ps)]).replace("\n", "\\n") + "`")
        if fn:
            lines.append("- missed (FN): " + ", ".join(f"`{r['text'][s:e]}` ({l})" for s, e, l in fn))
        if fp:
            lines.append("- spurious/boundary (FP): " + ", ".join(f"`{r['text'][s:e]}` ({l})" for s, e, l in fp))
        lines.append("")
    lines.insert(2, f"Total kalimat dengan kesalahan: **{n_err} / {len(rows)}**\n")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--kind", default="transformer", choices=["transformer", "crf"])
    ap.add_argument("--backend", default=None, choices=[None, "onnx", "torch"])
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--threads", type=int, default=None)
    args = ap.parse_args()

    model = load_model(args.model, args.kind, args.backend, args.threads)
    gold_rows = load_gold(DATA / "gold" / "test_gold.txt")
    dev_rows = load_jsonl(DATA / "generated" / "dev.jsonl")

    g_pred, g_lat = run(model, gold_rows, args.threshold)
    d_pred, _ = run(model, dev_rows, args.threshold)

    by_cat = defaultdict(list)
    for i, r in enumerate(gold_rows):
        by_cat[r["category"]].append(i)
    per_cat = {}
    for cat, idx in by_cat.items():
        m = evaluate_rows([gold_rows[i] for i in idx], [g_pred[i] for i in idx])
        per_cat[cat] = {"n": len(idx), "f1": m["micro"]["f1"], "recall": m["micro"]["recall"],
                        "precision": m["micro"]["precision"], "leak_rate": m["char"]["leak_rate"],
                        "over_redaction": m["char"]["over_redaction"]}

    q = statistics.quantiles(g_lat, n=100)
    report = {
        "name": args.name, "model": args.model, "kind": args.kind,
        "backend": getattr(model, "backend", "crf"),
        "threshold": args.threshold if args.threshold is not None else getattr(model, "default_threshold", None),
        "gold": evaluate_rows(gold_rows, g_pred), "gold_per_category": per_cat,
        "dev": evaluate_rows(dev_rows, d_pred),
        "latency_ms_single_message": {"mean": round(statistics.mean(g_lat), 2), "p50": round(q[49], 2),
                                      "p95": round(q[94], 2), "p99": round(q[98], 2)},
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{args.name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (REPORTS / f"{args.name}_errors.md").write_text(error_report(gold_rows, g_pred, args.name), encoding="utf-8")

    g, d = report["gold"], report["dev"]
    print(f"== {args.name}")
    print(f"gold strict  P={g['micro']['precision']:.3f} R={g['micro']['recall']:.3f} F1={g['micro']['f1']:.3f} F2={g['micro']['f2']:.3f}")
    for lab, v in g["per_label"].items():
        print(f"   {lab:8s} P={v['precision']:.3f} R={v['recall']:.3f} F1={v['f1']:.3f}  "
              f"lenient R={g['lenient']['per_label'][lab]['recall']:.3f}")
    print(f"gold lenient F1={g['lenient']['micro']['f1']:.3f} | leak={g['char']['leak_rate']:.4f} "
          f"over-redaction={g['char']['over_redaction']:.4f} clean-msg={g['char']['clean_message_rate']:.3f}")
    print(f"dev  strict  F1={d['micro']['f1']:.3f} leak={d['char']['leak_rate']:.4f}")
    print("per category:", json.dumps({k: (v['f1'], v['leak_rate']) for k, v in per_cat.items()}))
    print("latency ms:", report["latency_ms_single_message"])


if __name__ == "__main__":
    main()
