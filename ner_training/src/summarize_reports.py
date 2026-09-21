"""Aggregate evaluate.py reports (+ benchmark, if present) into one comparison table.

Usage:
    python summarize_reports.py
    python summarize_reports.py --md > ../reports/comparison.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "ner_training" / "reports"
BENCH_DIR = ROOT / "benchmark" / "results"


def load_reports() -> list[dict]:
    rows = []
    for p in sorted(REPORTS.glob("*.json")):
        if p.name == "stats.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if "gold" not in d:
            continue
        rows.append(d)
    return rows


def row(d: dict) -> dict:
    g, dev = d["gold"], d["dev"]
    return {
        "name": d["name"],
        "backend": d.get("backend", "-"),
        "dev_f1": dev["micro"]["f1"],
        "gold_f1": g["micro"]["f1"],
        "gold_lenient_f1": g["lenient"]["micro"]["f1"],
        "gold_recall": g["micro"]["recall"],
        "gold_leak_rate": g["char"]["leak_rate"],
        "gold_over_redaction": g["char"]["over_redaction"],
        "person_f1": g["per_label"].get("PERSON", {}).get("f1"),
        "address_f1": g["per_label"].get("ADDRESS", {}).get("f1"),
        "p50_ms": d["latency_ms_single_message"]["p50"],
        "p95_ms": d["latency_ms_single_message"]["p95"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="print a Markdown table instead of JSON")
    args = ap.parse_args()

    rows = [row(d) for d in load_reports()]
    benches = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(BENCH_DIR.glob("*.json"))} if BENCH_DIR.exists() else {}

    if not args.md:
        print(json.dumps({"models": rows, "benchmarks": benches}, indent=2))
        return

    print("| Model | Backend | Dev F1 | Gold F1 (strict) | Gold F1 (lenient) | Recall | Leak rate | Over-redaction | PERSON F1 | ADDRESS F1 | p50 ms | p95 ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['name']} | {r['backend']} | {r['dev_f1']} | {r['gold_f1']} | {r['gold_lenient_f1']} | "
              f"{r['gold_recall']} | {r['gold_leak_rate']} | {r['gold_over_redaction']} | {r['person_f1']} | "
              f"{r['address_f1']} | {r['p50_ms']} | {r['p95_ms']} |")

    if benches:
        print("\n| Benchmark | Backend | Model load (s) | RAM footprint (MB) | Peak RAM (MB) | p50 (ms) | p95 (ms) | p99 (ms) |")
        print("|---|---|---|---|---|---|---|---|")
        for name, b in benches.items():
            lat = b["single_message_latency_ms"]
            print(f"| {name} | {b['backend']} | {b['model_load']['seconds']} | "
                  f"{b['memory_mb']['model_footprint']} | {b['memory_mb']['peak_during_load_test']} | "
                  f"{lat['p50']} | {lat['p95']} | {lat['p99']} |")


if __name__ == "__main__":
    main()
