"""Baseline: linear-chain CRF with hand-crafted word features (sklearn-crfsuite).

Why a baseline? It answers "is the transformer worth its CPU/RAM cost?" with numbers.
A CRF trains in seconds, runs in ~1 ms, and needs a few MB of RAM — if it were nearly as
accurate, it would be the better engineering choice.

Usage:
    python train_crf.py --out ../models/crf
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
import time
from pathlib import Path

import sklearn_crfsuite

from annotation import bio_to_spans, load_jsonl, row_spans, spans_to_bio, tokenize_words
from metrics import span_metrics

DATA = Path(__file__).resolve().parent.parent / "data" / "generated"

ADDR_KEYS = {"jl", "jln", "jalan", "gg", "gang", "lr", "no", "nomor", "rt", "rw", "kel", "kelurahan", "kec",
             "kecamatan", "desa", "ds", "dusun", "kab", "kabupaten", "kota", "blok", "perum", "perumahan",
             "komplek", "kompleks", "komp", "apartemen", "apt", "cluster", "tower", "lt", "unit", "km", "kav",
             "kp", "kampung", "br", "ruko", "gedung", "wisma", "menara", "griya", "villa", "raya"}
PERSON_CUES = {"nama", "saya", "aku", "sy", "an", "a", "n", "bapak", "ibu", "pak", "bu", "mas", "mbak", "kak",
               "bang", "sdr", "sdri", "istri", "suami", "anak", "adik", "teknisi", "kurir", "penerima", "pemohon",
               "atas", "bernama", "namaku", "oleh", "dengan", "ini", "gw", "gue", "tuan", "nyonya", "hj", "h"}
PLACEHOLDER = re.compile(r"REDACT", re.I)


def word_features(words: list[str], i: int) -> dict:
    w = words[i]
    lw = w.lower()
    f = {
        "bias": 1.0, "w": lw, "suf3": lw[-3:], "pre3": lw[:3], "is_title": w.istitle(), "is_upper": w.isupper(),
        "is_digit": w.isdigit(), "len": min(len(w), 12), "is_punct": not w.isalnum(),
        "addr_key": lw in ADDR_KEYS, "person_cue": lw in PERSON_CUES, "placeholder": bool(PLACEHOLDER.search(w)),
        "shape": re.sub(r"[A-Z]", "X", re.sub(r"[a-z]", "x", re.sub(r"\d", "d", w)))[:6],
    }
    for off in (-3, -2, -1, 1, 2, 3):
        j = i + off
        if 0 <= j < len(words):
            lj = words[j].lower()
            f[f"{off}:w"] = lj
            f[f"{off}:addr_key"] = lj in ADDR_KEYS
            f[f"{off}:person_cue"] = lj in PERSON_CUES
            f[f"{off}:is_title"] = words[j].istitle()
            f[f"{off}:is_digit"] = words[j].isdigit()
        else:
            f[f"{off}:pad"] = True
    return f


def featurize(text: str):
    toks = tokenize_words(text)
    words = [t[0] for t in toks]
    return toks, [word_features(words, i) for i in range(len(words))]


class CrfPredictor:
    """Same interface as NerEngine.predict_batch (returns objects with start/end/label)."""

    def __init__(self, path: str | Path):
        with open(Path(path) / "crf.pkl", "rb") as f:
            self.crf = pickle.load(f)

    def predict_batch(self, texts: list[str], threshold: float | None = None):
        out = []
        for text in texts:
            toks, feats = featurize(text)
            tags = self.crf.predict_single(feats) if feats else []
            out.append([_E(s.start, s.end, s.label) for s in bio_to_spans(toks, tags, text)])
        return out


class _E:
    def __init__(self, start, end, label):
        self.start, self.end, self.label = start, end, label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "models" / "crf"))
    ap.add_argument("--c1", type=float, default=0.05)
    ap.add_argument("--c2", type=float, default=0.05)
    args = ap.parse_args()

    train = load_jsonl(DATA / "train.jsonl")
    dev = load_jsonl(DATA / "dev.jsonl")
    X, y = [], []
    for row in train:
        toks, feats = featurize(row["text"])
        X.append(feats)
        y.append(spans_to_bio(toks, row_spans(row)))

    t0 = time.time()
    crf = sklearn_crfsuite.CRF(algorithm="lbfgs", c1=args.c1, c2=args.c2, max_iterations=200,
                               all_possible_transitions=True)
    crf.fit(X, y)
    train_sec = time.time() - t0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "crf.pkl", "wb") as f:
        pickle.dump(crf, f)

    pred = CrfPredictor(out).predict_batch([r["text"] for r in dev])
    m = span_metrics([[tuple(e) for e in r["entities"]] for r in dev],
                     [[(e.start, e.end, e.label) for e in p] for p in pred], [r["text"] for r in dev])
    meta = {"model": "CRF (sklearn-crfsuite)", "c1": args.c1, "c2": args.c2, "train_sec": round(train_sec, 1),
            "dev_f1": m["micro"]["f1"], "dev_leak_rate": m["char"]["leak_rate"],
            "model_kb": round((out / "crf.pkl").stat().st_size / 1024, 1)}
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
