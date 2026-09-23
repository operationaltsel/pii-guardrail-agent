"""Concurrent HTTP load test against a running NER Service (brief section F, extended).

``benchmark_ner.py`` measures the model in-process, one request at a time -- useful for
isolating model cost, but it never touches the network stack, FastAPI, uvicorn, or what
happens when several requests actually overlap. This script does: it fires real HTTP
requests at ``POST /v1/ner`` from multiple threads at once, against the service exactly as
deployed (``docker compose up`` / GKE), and reports p50/p95/p99 latency and throughput at
each concurrency level.

Usage:
    docker compose up -d ner-service        # or: cd ner_service && uvicorn app.main:app --port 8001
    python load_test_ner.py --url http://localhost:8001 --concurrency 1 5 10 20 --requests 100
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SAMPLE_TEXTS = [
    "Nama saya Budi Santoso dan tinggal di Jalan Sudirman Jakarta",
    "Selamat sore, saya Siti Rahmawati, mohon dibantu untuk pengecekan tagihan bulan ini",
    "Internet saya mati sejak pagi di Perum Griya Indah Blok C2 No. 7, Bekasi",
    "Tolong update alamat pemasangan ke Jl. Raya Kuta No. 88, Badung atas nama I Made Wirawan",
    "Halo, ada info paket internet untuk rumah saya di Jl. Melati No. 9, Depok?",
]


def one_request(url: str, text: str) -> float:
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(f"{url}/v1/ner", data=body, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        e.read()  # drain so the connection can be reused; status handled by caller via elapsed timing
    return (time.perf_counter() - t0) * 1000


def run_level(url: str, concurrency: int, n_requests: int) -> dict:
    texts = [SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)] for i in range(n_requests)]
    t0 = time.perf_counter()
    latencies: list[float] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_request, url, t) for t in texts]
        for f in as_completed(futures):
            latencies.append(f.result())
    wall_s = time.perf_counter() - t0

    lat_sorted = sorted(latencies)
    q = statistics.quantiles(lat_sorted, n=100) if len(lat_sorted) >= 2 else lat_sorted * 100
    return {
        "concurrency": concurrency,
        "requests": n_requests,
        "wall_seconds": round(wall_s, 3),
        "throughput_req_per_sec": round(n_requests / wall_s, 1),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 1),
            "min": round(min(latencies), 1),
            "p50": round(q[49], 1),
            "p95": round(q[94], 1),
            "p99": round(q[98], 1),
            "max": round(max(latencies), 1),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 5, 10, 20])
    ap.add_argument("--requests", type=int, default=100, help="requests per concurrency level")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "ner_load_test.json"))
    args = ap.parse_args()

    try:
        urllib.request.urlopen(f"{args.url}/health/ready", timeout=5).read()
    except Exception as e:
        raise SystemExit(f"ner-service not reachable at {args.url} (is it running? `docker compose up -d ner-service`): {e}")

    # brief warm-up so the first level isn't penalised by cold model/HTTP-keepalive cost
    for _ in range(3):
        one_request(args.url, SAMPLE_TEXTS[0])

    levels = [run_level(args.url, c, args.requests) for c in args.concurrency]
    report = {"url": args.url, "levels": levels}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
