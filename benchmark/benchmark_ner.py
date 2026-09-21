"""Resource & performance benchmark for the NER model (brief section F).

Measures, on THIS machine, against the exact serving code path (``NerEngine`` +
ONNX Runtime):
* single-message latency (p50/p95/p99, cold start separated from warm)
* batch throughput (messages/sec at various batch sizes)
* peak process RSS memory during a sustained load
* CPU utilisation during a sustained load

Usage:
    python benchmark_ner.py --model ../ner_service/model --requests 200

Notes:
* Run with the CPU thread count you intend to deploy with (``--threads``, default 2, matching
  the k8s manifest's ``cpu: 1`` limit and ``NER_THREADS=1`` request — 2 gives headroom for the
  request handler thread while ORT inference uses 1).
* Uses the gold test set's texts as realistic input if available, else the dev set.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ner_service"))
sys.path.insert(0, str(ROOT / "ner_training" / "src"))


def load_texts(n: int) -> list[str]:
    from annotation import load_gold, load_jsonl

    gold = ROOT / "ner_training" / "data" / "gold" / "test_gold.txt"
    dev = ROOT / "ner_training" / "data" / "generated" / "dev.jsonl"
    texts = [r["text"] for r in load_gold(gold)] if gold.exists() else []
    if dev.exists():
        texts += [r["text"] for r in load_jsonl(dev)]
    if not texts:
        texts = ["Nama saya Budi Santoso dan tinggal di Jalan Sudirman Jakarta"] * n
    while len(texts) < n:
        texts += texts
    return texts[:n]


class CpuSampler:
    """Samples process CPU% in a background thread (psutil needs an interval to be meaningful)."""

    def __init__(self, proc: psutil.Process, interval: float = 0.2):
        self.proc, self.interval, self.samples, self._stop = proc, interval, [], False

    def __enter__(self):
        self.proc.cpu_percent(None)  # discard first (meaningless) reading
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop:
            self.samples.append(self.proc.cpu_percent(self.interval))

    def __exit__(self, *exc):
        self._stop = True
        self._thread.join(timeout=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(ROOT / "ner_service" / "model"))
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--batch-sizes", type=int, nargs="+", default=[1, 8, 32])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "ner_benchmark.json"))
    args = ap.parse_args()

    from app.inference import NerEngine

    proc = psutil.Process()
    mem_before_mb = proc.memory_info().rss / 2**20

    t_load0 = time.perf_counter()
    engine = NerEngine(args.model, threads=args.threads)
    load_sec = time.perf_counter() - t_load0
    mem_after_load_mb = proc.memory_info().rss / 2**20

    texts = load_texts(max(args.requests, max(args.batch_sizes) * 5))

    # cold start: first inference call pays ONNX Runtime graph warm-up cost
    t0 = time.perf_counter()
    engine.predict(texts[0])
    cold_start_ms = (time.perf_counter() - t0) * 1000

    # single-message latency distribution + CPU/memory under sustained load
    lat_ms, peak_rss_mb = [], mem_after_load_mb
    with CpuSampler(proc) as sampler:
        for t in texts[:args.requests]:
            t0 = time.perf_counter()
            engine.predict(t)
            lat_ms.append((time.perf_counter() - t0) * 1000)
            peak_rss_mb = max(peak_rss_mb, proc.memory_info().rss / 2**20)
    cpu_samples = [s for s in sampler.samples if s is not None]

    lat_ms_sorted = sorted(lat_ms)
    q = statistics.quantiles(lat_ms_sorted, n=100) if len(lat_ms_sorted) >= 2 else lat_ms_sorted * 100

    # batch throughput
    throughput = {}
    for bs in args.batch_sizes:
        batch_texts = texts[:bs]
        n_iters = max(3, args.requests // bs)
        t0 = time.perf_counter()
        for _ in range(n_iters):
            engine.predict_batch(batch_texts)
        dt = time.perf_counter() - t0
        throughput[str(bs)] = {"messages_per_sec": round(bs * n_iters / dt, 1), "ms_per_batch": round(dt / n_iters * 1000, 2)}

    report = {
        "model": str(args.model), "backend": engine.backend, "onnxruntime_threads": args.threads,
        "cpu_logical_cores": psutil.cpu_count(logical=True), "cpu_physical_cores": psutil.cpu_count(logical=False),
        "model_load": {"seconds": round(load_sec, 3), "cold_start_ms": round(cold_start_ms, 1)},
        "memory_mb": {"before_load": round(mem_before_mb, 1), "after_load": round(mem_after_load_mb, 1),
                     "peak_during_load_test": round(peak_rss_mb, 1),
                     "model_footprint": round(mem_after_load_mb - mem_before_mb, 1)},
        "cpu_percent_during_load_test": {
            "mean": round(statistics.mean(cpu_samples), 1) if cpu_samples else None,
            "max": round(max(cpu_samples), 1) if cpu_samples else None,
            "note": f"% of one core; {args.threads} ORT intra-op threads requested",
        },
        "single_message_latency_ms": {
            "n": len(lat_ms), "mean": round(statistics.mean(lat_ms), 2), "min": round(min(lat_ms), 2),
            "p50": round(q[49], 2), "p90": round(q[89], 2), "p95": round(q[94], 2), "p99": round(q[98], 2),
            "max": round(max(lat_ms), 2),
        },
        "batch_throughput": throughput,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
