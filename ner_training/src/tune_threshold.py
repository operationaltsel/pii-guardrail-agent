"""Pick the entity threshold on the DEV split (never on the gold test set).

A word is labelled as an entity when ``1 - P(O) >= threshold``. For a guardrail, a missed
entity (leak) is worse than an extra redaction, so we select the threshold that maximises
**F2** (recall weighted 2x) while keeping precision >= ``--min-precision``.

The chosen value is written into the model's ``model_card.json`` and becomes the service default.

Usage:
    python tune_threshold.py --model ../models/indobert-lite-onnx-int8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ner_service"))
from app.inference import NerEngine  # noqa: E402

from annotation import load_jsonl  # noqa: E402
from metrics import span_metrics  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--min-precision", type=float, default=0.90)
    args = ap.parse_args()

    engine = NerEngine(args.model)
    dev = load_jsonl(ROOT / "ner_training" / "data" / "generated" / "dev.jsonl")
    texts = [r["text"] for r in dev]
    gold = [[tuple(e) for e in r["entities"]] for r in dev]

    rows = []
    for thr in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7]:
        preds = engine.predict_batch(texts, thr)
        m = span_metrics(gold, [[(e.start, e.end, e.label) for e in p] for p in preds], texts)
        rows.append({"threshold": thr, "precision": m["micro"]["precision"], "recall": m["micro"]["recall"],
                     "f1": m["micro"]["f1"], "f2": m["micro"]["f2"], "leak_rate": m["char"]["leak_rate"],
                     "over_redaction": m["char"]["over_redaction"]})
        print(json.dumps(rows[-1]))

    ok = [r for r in rows if r["precision"] >= args.min_precision] or rows
    best = max(ok, key=lambda r: (r["f2"], -r["leak_rate"]))
    card_path = Path(args.model) / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.exists() else {}
    card.update(threshold=best["threshold"], threshold_selection={
        "criterion": f"max F2 on dev with precision >= {args.min_precision}", "dev_at_threshold": best, "sweep": rows})
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"\nselected threshold={best['threshold']} (dev F2={best['f2']}, recall={best['recall']}, "
          f"precision={best['precision']}, leak={best['leak_rate']})")


if __name__ == "__main__":
    main()
