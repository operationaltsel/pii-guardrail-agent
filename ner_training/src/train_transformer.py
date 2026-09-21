"""Fine-tune a pretrained Indonesian encoder (IndoBERT) for token classification (BIO).

Usage:
    python train_transformer.py --model indobenchmark/indobert-base-p1 --out ../models/indobert-base
    python train_transformer.py --model indobenchmark/indobert-lite-base-p1 --out ../models/indobert-lite --lr 1e-4

Why fine-tuning counts as "training our own NER model": the base checkpoint only knows
Indonesian language modelling; it has no notion of PERSON/ADDRESS. The classification head,
the label scheme, the data and the decision threshold are all ours.

A plain PyTorch loop (instead of HF Trainer) keeps every step explicit: label alignment,
optimiser, warm-up schedule, gradient clipping, early stopping on dev F1.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer, BertTokenizerFast

ROOT = Path(__file__).resolve().parents[2]

from annotation import BIO_LABELS, bio_to_spans, load_jsonl  # noqa: E402
from metrics import span_metrics  # noqa: E402

DATA = ROOT / "ner_training" / "data" / "generated"
LABEL2ID = {l: i for i, l in enumerate(BIO_LABELS)}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def load_tokenizer(model_id: str):
    # indobert-lite ships a BERT WordPiece vocab but an ALBERT config; AutoTokenizer in
    # transformers v5 mis-converts it, so force the WordPiece tokenizer explicitly.
    if "lite" in model_id:
        return BertTokenizerFast.from_pretrained(model_id)
    return AutoTokenizer.from_pretrained(model_id)


def encode(rows: list[dict], tokenizer, max_len: int) -> list[dict]:
    """Align character spans to sub-word tokens: first token of an entity gets B-, the rest I-."""
    feats = []
    for row in rows:
        enc = tokenizer(row["text"], truncation=True, max_length=max_len, return_offsets_mapping=True)
        labels = []
        for (s, e), wid in zip(enc["offset_mapping"], enc.word_ids()):
            if wid is None or s == e:
                labels.append(-100)
                continue
            tag = "O"
            for es, ee, lab in row["entities"]:
                if s >= es and e <= ee:
                    tag = ("B-" if s == es else "I-") + lab
                    break
            labels.append(LABEL2ID[tag])
        # a span start that falls inside a token (rare): make sure each entity has a B-
        feats.append({"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"], "labels": labels})
    return feats


def collate(batch, pad_id: int):
    width = max(len(b["input_ids"]) for b in batch)
    out = {k: torch.full((len(batch), width), v, dtype=torch.long)
           for k, v in (("input_ids", pad_id), ("attention_mask", 0), ("labels", -100))}
    for i, b in enumerate(batch):
        n = len(b["input_ids"])
        for k in out:
            out[k][i, :n] = torch.tensor(b[k])
    return out


def bucketed_batches(feats: list[dict], batch: int, seed: int, epoch: int) -> list[list[int]]:
    """Shuffle, then sort by length inside large chunks, so each batch has similar lengths.
    Cuts padding (and CPU time) substantially while keeping randomness between epochs."""
    rng = random.Random(seed + epoch)
    idx = list(range(len(feats)))
    rng.shuffle(idx)
    chunk = batch * 50
    batches = []
    for i in range(0, len(idx), chunk):
        part = sorted(idx[i:i + chunk], key=lambda k: len(feats[k]["input_ids"]))
        batches += [part[j:j + batch] for j in range(0, len(part), batch)]
    rng.shuffle(batches)
    return batches


def export_for_engine(model, tokenizer, out: Path) -> None:
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)  # writes tokenizer.json used by the serving engine
    (out / "labels.json").write_text(json.dumps({"labels": BIO_LABELS}, indent=2), encoding="utf-8")


def evaluate_dev(model, tokenizer, dev_rows: list[dict], max_len: int) -> dict:
    """In-process eval (no disk round-trip): reuses the live model, batched, on GPU/CPU as-is.
    Used every epoch for early stopping; the full disk-serialised model is evaluated end-to-end
    (including ONNX export) separately by evaluate.py after training."""
    model.eval()
    all_pred, all_gold, texts = [], [], [r["text"] for r in dev_rows]
    feats = encode(dev_rows, tokenizer, max_len)
    with torch.inference_mode():
        for i in range(0, len(feats), 32):
            chunk = feats[i:i + 32]
            batch = collate(chunk, tokenizer.pad_token_id)
            logits = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).logits
            pred_ids = logits.argmax(-1).tolist()
            for row, ids, f in zip(dev_rows[i:i + 32], pred_ids, chunk):
                enc = tokenizer(row["text"], truncation=True, max_length=max_len, return_offsets_mapping=True)
                tags = [BIO_LABELS[t] for t in ids[:len(enc["input_ids"])]]
                # collapse to one tag per *word* (first sub-token's tag). The span must extend to
                # the LAST sub-token's end, not the first's — a multi-subword word like "patricia"
                # ("patri" + "##cia") would otherwise be truncated to just its first piece.
                order, spans_by_word, tag_by_word = [], {}, {}
                for (s, e), wid, tag in zip(enc["offset_mapping"], enc.word_ids(), tags):
                    if wid is None or s == e:
                        continue
                    if wid not in spans_by_word:
                        order.append(wid)
                        spans_by_word[wid] = [s, e]
                        tag_by_word[wid] = tag  # first sub-token's tag is authoritative
                    else:
                        spans_by_word[wid][1] = e
                word_tags = [tag_by_word[w] for w in order]
                word_spans = [(row["text"][spans_by_word[w][0]:spans_by_word[w][1]], *spans_by_word[w]) for w in order]
                spans = bio_to_spans(word_spans, word_tags, row["text"])
                all_pred.append([(sp.start, sp.end, sp.label) for sp in spans])
            all_gold += [[tuple(x) for x in r["entities"]] for r in dev_rows[i:i + 32]]
    model.train()
    return span_metrics(all_gold, all_pred, texts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="indobenchmark/indobert-base-p1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=128)
    ap.add_argument("--warmup", type=float, default=0.1)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--patience", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="debug: use only N training rows")
    ap.add_argument("--max-steps", type=int, default=0, help="benchmark: stop after N steps")
    ap.add_argument("--eval-subset", type=int, default=250, help="dev rows used for per-epoch early stopping")
    args = ap.parse_args()

    set_seed(args.seed)
    if args.threads:
        torch.set_num_threads(args.threads)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    train_rows = load_jsonl(DATA / "train.jsonl")
    dev_rows = load_jsonl(DATA / "dev.jsonl")
    if args.limit:
        train_rows = train_rows[:args.limit]

    tokenizer = load_tokenizer(args.model)
    model = AutoModelForTokenClassification.from_pretrained(
        args.model, num_labels=len(BIO_LABELS),
        id2label=dict(enumerate(BIO_LABELS)), label2id=LABEL2ID)

    train_feats = encode(train_rows, tokenizer, args.max_len)
    steps_per_epoch = math.ceil(len(train_feats) / args.batch)

    no_decay = ("bias", "LayerNorm.weight", "layer_norm.weight")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": args.weight_decay},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optim = torch.optim.AdamW(groups, lr=args.lr)
    total = args.epochs * steps_per_epoch
    warm = int(total * args.warmup)
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim, lambda step: step / max(1, warm) if step < warm else max(0.0, (total - step) / max(1, total - warm)))

    n_params = sum(p.numel() for p in model.parameters())
    print(f"model={args.model} params={n_params/1e6:.1f}M train={len(train_rows)} dev={len(dev_rows)} "
          f"steps={total} threads={torch.get_num_threads()}", flush=True)

    history, best_f1, bad_epochs, t0 = [], -1.0, 0, time.time()
    for epoch in range(1, args.epochs + 1):
        model.train()
        running, te = 0.0, time.time()
        batches = bucketed_batches(train_feats, args.batch, args.seed, epoch)
        for step, idx in enumerate(batches, 1):
            batch = collate([train_feats[i] for i in idx], tokenizer.pad_token_id)
            if args.max_steps and step > args.max_steps:
                break
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()
            running += loss.item()
            if step % 50 == 0:
                print(f"  epoch {epoch} step {step}/{steps_per_epoch} loss {running/step:.4f} "
                      f"({(time.time()-te)/step:.2f}s/step)", flush=True)
        dev_subset = dev_rows if len(dev_rows) <= args.eval_subset else dev_rows[:args.eval_subset]
        dev = evaluate_dev(model, tokenizer, dev_subset, args.max_len)
        if args.max_steps:
            print(f"benchmark: {args.max_steps} steps in {time.time()-te:.1f}s "
                  f"({(time.time()-te)/args.max_steps:.2f}s/step, threads={torch.get_num_threads()})")
            return
        rec = {"epoch": epoch, "train_loss": round(running / steps_per_epoch, 4), "epoch_sec": round(time.time() - te, 1),
               "dev_f1": dev["micro"]["f1"], "dev_precision": dev["micro"]["precision"],
               "dev_recall": dev["micro"]["recall"], "dev_leak_rate": dev["char"]["leak_rate"],
               "per_label": {k: v["f1"] for k, v in dev["per_label"].items()}}
        history.append(rec)
        print(json.dumps(rec), flush=True)
        if dev["micro"]["f1"] > best_f1:
            best_f1, bad_epochs = dev["micro"]["f1"], 0
            model.eval()
            export_for_engine(model, tokenizer, out)
            print(f"  -> new best dev F1 {best_f1:.4f}, saved", flush=True)
        else:
            bad_epochs += 1
            if bad_epochs >= args.patience:
                print("  early stopping", flush=True)
                break

    meta = {"base_model": args.model, "params_millions": round(n_params / 1e6, 2), "train_rows": len(train_rows),
            "dev_rows": len(dev_rows), "hyperparams": {k: v for k, v in vars(args).items() if k not in ("out",)},
            "best_dev_f1": best_f1, "history": history, "train_minutes": round((time.time() - t0) / 60, 1),
            "hardware": f"CPU-only ({platform.processor()}, {os.cpu_count()} logical cores)", "torch": torch.__version__}
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"done in {meta['train_minutes']} min, best dev F1 {best_f1:.4f}")


if __name__ == "__main__":
    main()
