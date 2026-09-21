# Arsitektur

## Komponen

```
┌─────────────┐  HTTP/SSE ┌─────────────┐   HTTP    ┌────────────────────────────────────────┐
│   User      │──────────▶│  Chat UI     │──────────▶│  CS Agent  (Google ADK + Gemini)         │
│  (browser)  │◀──────────│  frontend/   │◀──────────│  agent/agents/cs_agent/                  │
└─────────────┘           └─────────────┘  reply    │                                          │
                           │  before_model_callback  ─┐               │
                           │  after_model_callback    │  PII          │
                           │  before_tool_callback    │  Guardrail    │
                           │  after_tool_callback    ─┘               │
                           │        │                                 │
                           │        │ HTTP POST /v1/ner (regex-       │
                           │        │ redacted text only)             │
                           │        ▼                                 │
                           │  ┌──────────────────────────────────┐   │
                           │  │ NER Service (FastAPI + ONNX Rt)   │   │
                           │  │ ner_service/ — separate process,  │   │
                           │  │ separate container, separate      │   │
                           │  │ deployment/scaling                │   │
                           │  └──────────────────────────────────┘   │
                           │        │                                 │
                           │        ▼                                 │
                           │  Gemini API (Google) ── only ever sees   │
                           │  text with PII replaced by placeholders  │
                           └────────────────────────────────────────┘
```

Two independently deployable services, as required by the brief ("NER Service sebagai
service terpisah"):

| Service | Path | Responsibility |
|---|---|---|
| **Chat UI** | [`frontend/`](../frontend) | Static HTML/CSS/JS customer-facing chat, talks to the CS Agent's REST API directly |
| **CS Agent** | [`agent/`](../agent) | Google ADK agent, conversation, tool-calling, orchestrates the guardrail |
| **NER Service** | [`ner_service/`](../ner_service) | Stateless REST API: text in, `PERSON`/`ADDRESS` entities out |

Offline / build-time only (not part of the runtime path):

| | Path | Responsibility |
|---|---|---|
| **NER training** | [`ner_training/`](../ner_training) | Dataset generation, CRF + transformer training, ONNX export, evaluation |
| **Benchmark** | [`benchmark/`](../benchmark) | CPU/RAM/latency measurement (brief section F) |
| **Deploy** | [`deploy/`](../deploy) | Dockerfiles (in each service), docker-compose, Kubernetes manifests |

## Alur satu pesan (ringkas)

1. User mengirim teks ke Agent.
2. **`before_model_callback`** (di [`callbacks.py`](../agent/agents/cs_agent/guardrail/callbacks.py))
   berjalan **sebelum** Gemini dipanggil:
   a. Nilai PII yang sudah dikenal dari giliran sebelumnya (vault) diganti tokennya lagi.
   b. **Regex** mendeteksi & meredaksi NIK, email, telepon.
   c. Teks yang *sudah* diredaksi regex dikirim ke **NER Service**; hasilnya dipakai
      meredaksi Nama & Alamat.
   d. Kalau NER Service tidak bisa dihubungi: **fail-closed** (default) — pesan asli
      ditahan, agent membalas pesan gangguan sistem tanpa memanggil Gemini sama sekali.
3. Gemini menerima teks yang isinya sudah `[REDACT_NAMA_1]`, `[REDACT_ADDRESS_1]`, dst.
4. Kalau Gemini memanggil tool (mis. `buat_tiket_pengaduan`) dengan argumen berisi token,
   **`before_tool_callback`** menukar token → nilai asli **hanya untuk pemanggilan tool
   ini** (tool butuh data asli untuk bekerja).
5. Hasil tool diredaksi lagi oleh **`after_tool_callback`** sebelum masuk ke riwayat yang
   akan dibaca Gemini pada giliran berikutnya.
6. **`after_model_callback`** mengembalikan token pada balasan Gemini menjadi nilai asli
   milik user itu sendiri, sehingga yang ditampilkan ke user tetap natural
   ("Baik Kak Budi Santoso...").

Detail lengkap tiap langkah: [guardrail.md](guardrail.md).

## Kenapa dipisah begini

* **NER sebagai service terpisah** memenuhi requirement eksplisit di brief, dan secara
  arsitektur masuk akal: NER adalah beban kerja CPU-bound yang scaling-nya beda dari agent
  (yang I/O-bound, menunggu Gemini). Dipisah supaya bisa di-scale, dan bila alat gagal,
  agent tetap tersedia.
* **Regex sebelum NER** = data minimisation. NIK/email/telepon punya bentuk pasti dan tidak
  butuh model; mengirim teks yang sudah bersih dari itu ke NER Service mengurangi radius
  ledakan bila service itu suatu saat disusupi atau log-nya bocor.
* **Guardrail di `before_model_callback`**, bukan di dalam tool atau prompt — ini yang
  diminta brief eksplisit, dan alasannya kuat: guardrail yang bergantung pada LLM untuk
  "berperilaku baik" bisa dilewati oleh prompt injection; guardrail di lapisan callback
  berjalan di luar kendali model, selalu dieksekusi, dan tidak bisa "dibujuk" untuk
  dilewati.
