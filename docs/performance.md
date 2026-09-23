# Resource & Performance (brief bagian F)

Diukur oleh [`benchmark/benchmark_ner.py`](../benchmark/benchmark_ner.py) langsung
terhadap kode serving sesungguhnya (`NerEngine` + ONNX Runtime, backend yang sama persis
dengan yang dipakai [`ner_service`](../ner_service) saat runtime — bukan angka dari
notebook terpisah). Hasil mentah:
[`ner_benchmark_lite.json`](../benchmark/results/ner_benchmark_lite.json) (model yang
dipakai layanan) dan
[`ner_benchmark_base.json`](../benchmark/results/ner_benchmark_base.json) (pembanding).
Reproduksi: `make benchmark` (lite) / lihat [Makefile](../Makefile) untuk base.

## Mesin uji

| | |
|---|---|
| CPU | Intel Core i7-1260P (12 core / 16 thread) |
| RAM | 16 GB |
| OS | Windows 11 (dev). Manifest [`deploy/k8s/ner-service.yaml`](../deploy/k8s/ner-service.yaml) memberi margin di atas angka ini (limit 1 CPU penuh vs 2 ORT thread yang diukur di sini) karena container Linux di GKE biasanya sedikit lebih efisien daripada proses Python di Windows, dan margin ekstra menyerap variasi node. |
| ORT threads | 2 (`NER_THREADS=2`, sesuai `resources.requests.cpu` di manifest k8s) |
| Beban saat ukur | Mesin **tidak** idle — proses training model pembanding (IndoBERT-base) masih berjalan di background saat sebagian benchmark ini diambil. Angka di bawah karena itu adalah **batas atas yang konservatif**; di server produksi yang idle, latency akan sama atau lebih baik. |

## Model footprint

| | CRF | **IndoBERT-lite** (dipakai layanan) | IndoBERT-base (pembanding) |
|---|---|---|---|
| Parameter | — | 11,1 juta | 123,9 juta |
| Ukuran file (int8 ONNX) | 360 KB | **38,1 MB** | 119,3 MB |
| RAM setelah model dimuat | ~5 MB (perkiraan, tidak diukur `benchmark_ner.py`) | **77,6 MB** | 162,4 MB |
| RAM puncak saat 200 request beruntun | — | **115,5 MB** | 200,5 MB |
| Waktu load model (cold start proses) | < 0,1 s | **0,63 s** | 0,59 s |
| Latency inferensi pertama (cold) | — | 25,0 ms | 11,9 ms |

## Latency inferensi (per pesan tunggal, pola panggilan produksi — 1 pesan/panggilan, bukan batch)

| Model | mean | p50 | p90 | p95 | p99 |
|---|---|---|---|---|---|
| CRF | — | 0,7 ms | — | 1,8 ms | 3,1 ms |
| **IndoBERT-lite (int8)** | 37,2 ms | **32,3 ms** | 56,2 ms | **62,1 ms** | 104,8 ms |
| IndoBERT-base (int8) | 18,7 ms | 15,5 ms | 29,8 ms | 42,5 ms | 76,5 ms |

Angka CRF dari `ner_training/reports/crf.json` (`evaluate.py`, pola panggilan yang sama).
CRF jelas tercepat (mikrodetik, bukan milidetik) karena tidak ada forward pass neural
network — ini bagian dari trade-off yang didiskusikan di [ner_model.md § 6](ner_model.md#6-model-yang-dipilih-untuk-layanan).

**Base lebih cepat dari lite di sini** meski parameternya 11× lebih banyak — hasil yang
kontra-intuitif tapi konsisten di dua metodologi pengukuran berbeda (`evaluate.py` *dan*
`benchmark_ner.py`), jadi bukan kebetulan pengukuran. Penjelasan paling mungkin: ALBERT
(basis lite) tetap menjalankan 12 layer transformer penuh per forward pass (berbagi bobot
mengecilkan file, bukan mengurangi FLOPs), ditambah operasi *factorized embedding*
tambahan yang graph-nya tidak seefisien BERT standar saat dikuantisasi int8 oleh ONNX
Runtime. Lihat [ner_model.md § 6](ner_model.md#6-model-yang-dipilih-untuk-layanan) untuk
bagaimana ini ditimbang terhadap RAM dan akurasi dalam memilih model yang dipakai layanan.

Semua p95 di atas **jauh di bawah** `NER_TIMEOUT_S=3.0` (detik) yang dikonfigurasi pada
guardrail — ada margin ~50-250× sebelum guardrail dianggap "lambat" dan sirkuit
breaker/fail-closed aktif (lihat [guardrail.md § 2](guardrail.md#2-ner-nama--alamat)).

## CPU & throughput batch

| | IndoBERT-lite | IndoBERT-base |
|---|---|---|
| CPU rata-rata saat load test (dari 2 ORT thread) | 194% | 193% |
| Throughput batch=1 | 44,0 pesan/detik | 67,1 pesan/detik |
| Throughput batch=8 | 22,1 pesan/detik | 38,3 pesan/detik |
| Throughput batch=32 | 13,0 pesan/detik | 22,5 pesan/detik |

Throughput batch **menurun** seiring ukuran batch membesar untuk kedua model — wajar di
CPU (bukan GPU): tidak ada percepatan paralel lintas-request di dalam satu forward pass
CPU, jadi batching di sini hanya berguna untuk mengurangi *overhead* Python per-panggilan,
bukan untuk mempercepat komputasi inti. Endpoint `/v1/ner/batch` disediakan untuk
kasus penggunaan non-real-time (mis. audit ulang riwayat chat), bukan jalur utama
guardrail (yang selalu satu pesan per panggilan).

## Load test HTTP nyata (concurrency)

Semua angka di atas diukur **in-process**, satu panggilan berurutan langsung ke
`NerEngine` — tidak pernah menyentuh jaringan, FastAPI, atau uvicorn, dan tidak pernah
lebih dari satu request pada satu waktu. Untuk melihat apa yang sebenarnya terjadi saat
beberapa klien memukul endpoint HTTP secara bersamaan (skenario nyata: beberapa sesi chat
aktif sekaligus), [`benchmark/load_test_ner.py`](../benchmark/load_test_ner.py) mengirim
request `POST /v1/ner` sungguhan lewat jaringan ke container `ner-service` yang sedang
jalan (`docker compose up`), dari beberapa thread sekaligus, pada beberapa level
concurrency. Hasil mentah: [`ner_load_test.json`](../benchmark/results/ner_load_test.json).
Reproduksi: `make load-test-ner` (butuh `ner-service` sudah jalan).

| Concurrency | Throughput (req/s) | p50 | p95 | p99 |
|---|---|---|---|---|
| 1  | 12,4 | 84 ms    | 118 ms   | 191 ms   |
| 5  | 10,8 | 412 ms   | 787 ms   | 1.183 ms |
| 10 | 9,9  | 999 ms   | 1.303 ms | 1.498 ms |
| 20 | 10,4 | 1.846 ms | 2.501 ms | 3.181 ms |

**Temuan kunci: throughput mendatar di ~10-12 req/detik di semua level concurrency** —
menambah klien dari 1 ke 20 tidak menambah throughput sama sekali, hanya menambah antrean
(p50 naik dari 84 ms ke 1.846 ms secara linear terhadap concurrency). Ini konsisten dengan
hasil "CPU & throughput batch" di atas: instance ini terikat CPU pada ~2 ORT thread
(`NER_THREADS=2`, `limits.cpu: "1"` di manifest k8s), jadi satu instance punya plafon
throughput yang keras, bukan yang melambat secara bertahap.

**Implikasi sizing**: menaikkan `NER_THREADS`/CPU limit satu instance hanya menggeser
plafon sedikit (dan bersaing dengan proses lain di node yang sama). Respons yang benar
terhadap beban tinggi adalah **horizontal**, bukan vertikal — persis yang sudah
dikonfigurasi `HorizontalPodAutoscaler` di
[`deploy/k8s/ner-service.yaml`](../deploy/k8s/ner-service.yaml) (`minReplicas: 2,
maxReplicas: 8`, scale on CPU): di atas ~10-12 req/detik sustained, HPA menambah pod baru
alih-alih membiarkan satu pod mengantre semakin panjang.

## Interpretasi untuk sizing

* **Latency**: p99 IndoBERT-lite (104,8 ms) memberi margin besar di bawah `NER_TIMEOUT_S`
  (3.000 ms) yang dikonfigurasi guardrail — bahkan di mesin yang sedang terbebani
  training lain. `readinessProbe`/`startupProbe` di
  [`deploy/k8s/ner-service.yaml`](../deploy/k8s/ner-service.yaml) menggunakan interval
  yang jauh lebih longgar dari ini.
* **RAM**: puncak terukur 115,5 MB (lite) berada nyaman di bawah `limits.memory: 512Mi`
  pada manifest k8s, menyisakan ruang untuk proses FastAPI/uvicorn itu sendiri dan lonjakan
  sementara.
* **CPU**: ~2 core termanfaatkan penuh (194%) sesuai `NER_THREADS=2`; manifest memberi
  `limits.cpu: "1"` (setara 100% dari 1 core) yang **lebih rendah** dari yang diukur di
  sini secara sengaja — di produksi, `NER_THREADS` diset mengikuti CPU limit sebenarnya
  (lihat komentar di `Dockerfile`/manifest), bukan disamakan dengan mesin dev 16-thread ini.
* Trade-off akurasi vs latency vs RAM lengkap antar ketiga model, dan alasan pemilihan
  akhir: [ner_model.md § 5–6](ner_model.md#5-hasil).
