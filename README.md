# AI Agent Customer Support dengan PII Guardrail

Take-home test — Internship AI Engineer (Infomedia). Agent customer support berbasis
**Google ADK + Gemini** dengan guardrail PII dua lapis: **regex** (NIK, email, telepon)
dan **NER model buatan sendiri** (Nama, Alamat) yang di-deploy sebagai **service
terpisah**.

> Untuk memahami cara berpikirnya secara singkat, mulai dari [docs/architecture.md](docs/architecture.md).

## Daftar isi

- [Arsitektur singkat](#arsitektur-singkat)
- [Cara menjalankan](#cara-menjalankan)
- [Penjelasan guardrail](#penjelasan-guardrail)
- [Contoh input–output](#contoh-inputoutput)
- [Struktur repo](#struktur-repo)
- [Dokumentasi lengkap](#dokumentasi-lengkap)
- [Status checklist brief](#status-checklist-brief)

## Arsitektur singkat

```
User ─▶ CS Agent (Google ADK + Gemini) ─┐
         before_model_callback:          │  HTTP POST /v1/ner
           1. vault (PII giliran lalu)   │  (hanya teks yang sudah
           2. regex → NIK/Email/Telepon  ├─▶  bersih dari regex)
           3. HTTP → NER Service         │
              → redact Nama & Alamat     │  NER Service (FastAPI + ONNX)
         Gemini hanya menerima teks      │  model IndoBERT fine-tuned sendiri
         yang sudah diredaksi            │  (PERSON, ADDRESS)
```

Dua service independen, masing-masing dengan Dockerfile dan bisa di-deploy/scale
terpisah: [`agent/`](agent) dan [`ner_service/`](ner_service). Detail lengkap +
alasan desain: [docs/architecture.md](docs/architecture.md).

## Cara menjalankan

### Opsi A — Docker Compose (paling cepat, model sudah termasuk di repo)

```bash
cp .env.example .env        # isi GOOGLE_API_KEY (https://aistudio.google.com/apikey)
docker compose up --build
```

* NER Service: http://localhost:8001/docs (Swagger), health: `/health/ready`
* CS Agent: http://localhost:8000 (`adk api_server`), coba lewat `adk web` untuk UI chat
  (lihat Opsi B) atau lewat `curl`/Postman ke endpoint ADK standar.

### Opsi B — Lokal, tanpa Docker (untuk development / `adk web` UI interaktif)

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r ner_service/requirements.txt
pip install -r agent/requirements.txt

# terminal 1 — NER Service
cd ner_service && uvicorn app.main:app --port 8001

# terminal 2 — Agent (model NER sudah ter-bundle, tidak perlu training ulang)
export GOOGLE_API_KEY=xxx NER_SERVICE_URL=http://localhost:8001
cd agent && adk web agents          # UI chat di http://localhost:8000
# atau: adk run agents/cs_agent     # chat di terminal
```

### Menjalankan test

```bash
make test-guardrail   # 44 test: regex, vault, redactor, end-to-end lewat ADK asli
make test-service     # test kontrak REST API NER Service
```

### Reproduksi model dari nol (opsional — model hasil training sudah ada di `ner_service/model/`)

```bash
pip install -r ner_training/requirements.txt
make dataset          # generate dataset sintetis (train/dev)
make train-crf        # baseline CRF (~1 menit)
make train-lite       # fine-tune IndoBERT-lite (~20-30 menit di CPU)
make export-onnx      # export + kuantisasi int8 → ner_service/model/
make tune-threshold   # pilih threshold optimal di data dev
make evaluate-model   # metrik lengkap di dev + gold test set
make benchmark        # CPU/RAM/latency
```

Lihat [Makefile](Makefile) untuk daftar target lengkap.

## Penjelasan guardrail

**Regex** (NIK/Email/Telepon) — regex baseline dari brief punya tiga bug (NIK: `^$` hanya
cocok bila pesan *seluruhnya* NIK; Email: titik tak di-escape; Telepon: `+` tak di-escape
→ `re.error`) yang diperbaiki dan diuji eksplisit. Detail lengkap + tabel
sebelum/sesudah: [docs/guardrail.md § 1](docs/guardrail.md#1-regex-nik-email-telepon).

**NER** (Nama/Alamat) — model IndoBERT fine-tuned sendiri (bukan pretrained NER),
dilatih pada dataset sintetis 6.000 kalimat customer-support Bahasa Indonesia +
dievaluasi pada 135 kalimat gold yang ditulis manual. Metodologi dataset, kontrol
kebocoran data, dan hasil evaluasi lengkap: [docs/ner_model.md](docs/ner_model.md).

**Integrasi & urutan pipeline** (vault → regex → NER, dijalankan di `before_model_callback`
ADK, sebelum Gemini dipanggil), **fail-closed** saat NER Service down, dan desain vault
reversibel untuk tool-calling: [docs/guardrail.md](docs/guardrail.md).

## Contoh input–output

Contoh dari brief, berjalan end-to-end (mode `mask`, `PII_REDACTION_MODE=mask`):

| Input | Output (yang dilihat Gemini) |
|---|---|
| `Nama saya Budi, saya tinggal di Jl.ABC` | `Nama saya [REDACT_NAMA], saya tinggal di [REDACT_ADDRESS]` |

Mode default (`pseudonymize`, reversibel — lihat [docs/guardrail.md § 4](docs/guardrail.md#4-vault-redaksi-yang-reversibel)):

| Giliran | User → Guardrail → Gemini | Gemini → Guardrail → User |
|---|---|---|
| 1 | `Halo, saya Budi Santoso, HP 0812-3456-7890. Internet di Jl. Mawar No. 5, Bandung mati.` → `Halo, saya [REDACT_NAMA_1], HP [REDACT_PHONE_1]. Internet di [REDACT_ADDRESS_1] mati.` | Gemini memanggil tool `buat_tiket_pengaduan` dengan argumen berisi token; tool menerima **nilai asli** (`Budi Santoso`, `0812-3456-7890`, alamat asli) → balasan model: `Baik Kak [REDACT_NAMA_1], tiket TKT-1001 sudah dibuat.` → user melihat: `Baik Kak Budi Santoso, tiket TKT-1001 sudah dibuat.` |
| 2 | `terima kasih` → (riwayat giliran 1 ditokenkan ulang, tidak ada PII mentah yang terkirim ke Gemini pada giliran mana pun) | `Sama-sama Kak Budi Santoso!` |

Skenario ini adalah `test_no_raw_pii_reaches_llm_and_tool_gets_real_values` di
[`agent/tests/test_agent_e2e.py`](agent/tests/test_agent_e2e.py) — dijalankan lewat
`InMemoryRunner` ADK asli dengan LLM palsu yang merekam **setiap** request, lalu
diverifikasi tidak ada satu pun nilai PII mentah muncul di request mana pun.

Lebih banyak contoh (regex, NER, percakapan multi-giliran dengan tool call, fail-closed,
kasus negatif): [docs/example_transcript.md](docs/example_transcript.md). Kesalahan model
konkret: `*_errors.md` di `ner_training/reports/` setelah `make evaluate-model`.

## Struktur repo

```
agent/            CS Agent — Google ADK, guardrail, tools, tests
ner_service/       NER Service — FastAPI + ONNX Runtime, model, tests
ner_training/      Dataset generation, training (CRF & transformer), evaluasi
benchmark/         Pengukuran CPU/RAM/latency (brief bagian F)
deploy/k8s/        Manifest Kubernetes (bonus — brief bagian G)
docs/              Dokumentasi detail (arsitektur, guardrail, model, performa, deployment)
docker-compose.yml Menjalankan kedua service sekaligus secara lokal
Makefile           Semua perintah build/train/test/benchmark
```

## Dokumentasi lengkap

| Dokumen | Isi |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Diagram komponen, alur satu pesan, alasan desain |
| [docs/guardrail.md](docs/guardrail.md) | Regex (bug & perbaikan), NER client, vault, fail-closed/open |
| [docs/ner_model.md](docs/ner_model.md) | Dataset, anotasi, kontrol kebocoran data, arsitektur model, hasil evaluasi |
| [docs/performance.md](docs/performance.md) | CPU, memory, latency (brief bagian F) |
| [docs/deployment.md](docs/deployment.md) | Rencana deploy GKE (bonus — brief bagian G) |
| [docs/example_transcript.md](docs/example_transcript.md) | Contoh input–output lengkap: regex, NER, tool-calling, fail-closed |

## Status checklist brief

- [x] A. AI Agent (Google ADK, Gemini ≥2.0, guardrail di `before_model_callback`)
- [x] B. Guardrail Regex (NIK, Email, Telepon + redaksi)
- [x] C. Guardrail NER (model dilatih sendiri, entity Nama & Alamat, ≥10 data uji)
- [x] D. NER Service terpisah (REST API)
- [x] E. Integrasi (agent memanggil NER Service via HTTP)
- [x] F. Dokumentasi resource (CPU/Memory/latency)
- [ ] G. Bonus: deploy ke GKE — manifest lengkap disiapkan & diverifikasi via docker
      compose, deploy sungguhan tidak dijalankan (butuh akun GCP berbayar) — lihat
      [docs/deployment.md](docs/deployment.md)
