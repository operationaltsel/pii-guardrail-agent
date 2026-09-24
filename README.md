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
                    ┌─ frontend/ (chat UI, :3100) ─┐
                    │   HTML/CSS/JS statis,          │
                    │   terhubung ke REST API ADK    │
                    └───────────────┬─────────────────┘
                                    ▼
User ─▶ CS Agent (Google ADK + Gemini) ─┐
         before_model_callback:          │  HTTP POST /v1/ner
           1. vault (PII giliran lalu)   │  (hanya teks yang sudah
           2. regex → NIK/Email/Telepon  ├─▶  bersih dari regex)
           3. HTTP → NER Service         │
              → redact Nama & Alamat     │  NER Service (FastAPI + ONNX)
         Gemini hanya menerima teks      │  model IndoBERT fine-tuned sendiri
         yang sudah diredaksi            │  (PERSON, ADDRESS)
```

Tiga service independen, masing-masing dengan Dockerfile dan bisa di-deploy/scale
terpisah: [`frontend/`](frontend) (chat UI customer-facing), [`agent/`](agent) (Google ADK
+ guardrail), [`ner_service/`](ner_service) (NER model). Detail lengkap + alasan desain:
[docs/architecture.md](docs/architecture.md).

## Cara menjalankan

### Opsi A — Docker Compose (paling cepat, model sudah termasuk di repo)

```bash
cp .env.example .env        # isi GOOGLE_API_KEY (https://aistudio.google.com/apikey)
docker compose up --build
```

* **Chat UI: http://localhost:3100** — ini yang dipakai pengguna akhir (lihat [frontend/](frontend))
* NER Service: http://localhost:8001/docs (Swagger), health: `/health/ready`
* CS Agent (API mentah): http://localhost:8000 — `adk api_server`, endpoint ADK standar
  (`/run_sse`, `/apps/.../sessions`, dst.) untuk integrasi atau `curl`/Postman

### Opsi B — Lokal, tanpa Docker (untuk development / `adk web` konsol developer)

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r ner_service/requirements.txt
pip install -r agent/requirements.txt

# terminal 1 — NER Service
cd ner_service && uvicorn app.main:app --port 8001

# terminal 2 — Agent (model NER sudah ter-bundle, tidak perlu training ulang)
export GOOGLE_API_KEY=xxx NER_SERVICE_URL=http://localhost:8001
cd agent && adk api_server agents --allow_origins http://localhost:3100

# terminal 3 — Chat UI
cd frontend && python -m http.server 3100   # buka http://localhost:3100
```

Untuk konsol developer ADK (debug event/trace mentah, bukan untuk pengguna akhir):
`adk web agents` (ganti terminal 2 di atas) → http://localhost:8000.

### Akun pelanggan demo

Mock backend ([agent/agents/cs_agent/db.py](agent/agents/cs_agent/db.py)) di-seed dengan 3
pelanggan Ventra fiktif. Sengaja bisa dicari di chat pakai nomor pelanggan, nomor HP,
**atau** nama — kebanyakan pelanggan asli tidak hafal ID internal 10 digit, jadi agent
(`cari_pelanggan`, lihat [agent/agents/cs_agent/tools.py](agent/agents/cs_agent/tools.py))
mencocokkan dari apa pun yang disebutkan lebih dulu:

| Nomor Pelanggan | Nama | No. HP | Alamat Pemasangan | Paket | Status Bayar |
|---|---|---|---|---|---|
| `1122334455` | Budi Santoso | `081234567890` | Jl. Sudirman No. 10, Jakarta Pusat | VentraFiber 50 Mbps | BELUM LUNAS |
| `2233445566` | Siti Rahmawati | `085711223344` | Perum Griya Indah Blok C2 No. 7, Bekasi | VentraFiber 100 Mbps | LUNAS |
| `3344556677` | I Made Wirawan | `081399887766` | Jl. Raya Kuta No. 88, Badung | VentraFiber 30 Mbps | BELUM LUNAS |

Alamat ini juga contoh siap pakai untuk menguji deteksi NER (label ADDRESS) — nama pelanggan
di atas untuk menguji deteksi NER (label PERSON).

Data ini persisten di SQLite (volume `cs-agent-data`) — bertahan lintas restart container,
reset hanya kalau volume-nya dihapus (`docker compose down -v`). Tiket pengaduan yang dibuat
lewat chat juga tersimpan di sana, bisa dicek lagi lewat "Cek status tiket".

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

### Skrip uji coba — bisa langsung diketik di chat (http://localhost:3100)

Semua baris di bawah ini bisa langsung dicoba tanpa setup tambahan, memakai 3 akun demo di
atas. Dikelompokkan supaya gampang dipilih saat demo langsung.

**A. Alur customer service (tool-calling, data dari SQLite)**

| # | Ketik ini | Yang terjadi |
|---|---|---|
| 1 | "Cek tagihan saya, nomor pelanggan 1122334455" | `cek_tagihan` → Budi Santoso, VentraFiber 50 Mbps, Rp385.000, **BELUM LUNAS** |
| 2 | "Cek tagihan nomor hp 085711223344" (tanpa sebut nomor pelanggan) | dicocokkan dari nomor HP → Siti Rahmawati, **LUNAS** |
| 3 | "Saya lupa nomor pelanggan saya, nama saya I Made Wirawan" | `cari_pelanggan` mencocokkan dari nama persis → data lengkap tampil |
| 4 | "Internet saya di rumah mati total, tolong dong" | agent **minta maaf dulu** (empati) sebelum minta nomor pelanggan/HP — bukan langsung minta data |
| 5 | lanjutan dari #4: sebut nomor pelanggan → "buatkan tiket saja" | `buat_tiket_pengaduan` dipanggil, dapat nomor tiket baru (format `TKT-xxxx`) |
| 6 | "Cek status tiket TKT-1001" (pakai nomor tiket dari langkah 5) | `cek_status_tiket` → status `DIBUKA` + estimasi penanganan besok |
| 7 | "Saya mau pindah alamat pemasangan ke Jl. Melati No. 8, Depok, nomor pelanggan 2233445566" | `ubah_alamat_pemasangan` → alamat baru tersimpan, biaya Rp150.000, survei 1-3 hari kerja |
| 8 | "Ada gangguan di Bekasi?" | `cek_gangguan_wilayah` → gangguan massal (kabel optik putus), estimasi normal 21:00 WIB |
| 9 | "Ada gangguan di Bandung?" | pemeliharaan terjadwal 01:00-04:00 WIB |
| 10 | "Ada gangguan di Badung?" | tidak ada gangguan tercatat (kota di luar data gangguan — negative case) |
| 11 | "Gimana cara restart modem?" / "lampu LOS merah kenapa?" / "gimana cara bayar?" / "paket apa aja yang tersedia?" | `cari_faq` mencocokkan dari 7 topik FAQ (lihat `_FAQ` di [tools.py](agent/agents/cs_agent/tools.py)) |
| 12 | "Cek tagihan nomor pelanggan 9999999999" (nomor asal) | `status: "error"`, "Nomor pelanggan tidak ditemukan." — agent tidak mengulang minta data yang sama, tawarkan cara lain (nomor HP/nama) |

**B. Guardrail PII — deteksi & redaksi (bisa dites lepas dari akun demo)**

| # | Ketik ini | Yang dibuktikan |
|---|---|---|
| 1 | "NIK saya 3273011506900001, tolong dicatat" | NIK terdeteksi di **tengah kalimat** — bug regex asli brief (`^...$`) cuma cocok kalau *seluruh* pesan adalah NIK, sudah diperbaiki (detail: [docs/guardrail.md § 1](docs/guardrail.md#1-regex-nik-email-telepon)) |
| 2 | "NIK saya 3273 0115 0690 0001" (pakai spasi) | tetap terdeteksi — regex baru mendukung NIK berspasi + validasi struktur (kode provinsi, tanggal lahir) |
| 3 | "HP saya +62 812-3456-7890" | telepon terdeteksi — regex asli brief (`+` tak di-escape di dalam `(+62\|...)`) crash `re.error` saat `re.compile()`, bukan cuma gagal match; sudah diperbaiki |
| 4 | "email saya budi@gmailxcom" (sengaja **tanpa** titik) | **tidak** terdeteksi sebagai email — benar, karena memang bukan email valid (regex asli brief salah: titik tak di-escape berarti cocok dengan karakter apa pun, jadi `budi@gmailxcom` lolos sebagai "valid") |
| 5 | "email saya budi@gmail.com" | terdeteksi sebagai EMAIL (pembanding langsung dari kasus #4) |
| 6 | "Saya Dian, NIK 3171234501900001, HP +62 812-3456-7890, email dian@yahoo.co.id" | ketiganya terdeteksi sekaligus dalam satu kalimat, urutan NIK → telepon → email |
| 7 | "halo min sy rizky ramadhan, wifi dirumah mati terus nih" | NAMA terdeteksi oleh **NER**, gaya bahasa informal, tanpa pola regex apa pun |
| 8 | "kak paketnya kirim ke jl melati no 5 bekasi ya" | ALAMAT terdeteksi oleh NER dari kalimat informal |
| 9 | "Saya mau jalan-jalan ke Bali bulan depan, apakah roaming aktif otomatis?" | **tidak ada** yang diredaksi — "Bali" bukan PII (negative test, membuktikan tidak over-redaksi) |
| 10 | "Apakah ada gangguan jaringan di Surabaya hari ini?" | **tidak ada** yang diredaksi — nama kota berdiri sendiri bukan ALAMAT |

Opsional — fail-closed saat NER Service mati (`docker compose stop ner-service`, coba kirim
pesan berisi nama/alamat, lalu `docker compose start ner-service` lagi): agent menolak
memproses dengan pesan "sistem perlindungan data kami sedang mengalami gangguan..." alih-alih
mengirim data mentah ke Gemini. Lihat [docs/example_transcript.md § 6](docs/example_transcript.md#6-ner-service-tidak-bisa-dihubungi).

## Struktur repo

```
frontend/          Chat UI customer-facing (HTML/CSS/JS statis, tanpa build step)
agent/             CS Agent — Google ADK, guardrail, tools, tests
ner_service/       NER Service — FastAPI + ONNX Runtime, model, tests
ner_training/      Dataset generation, training (CRF & transformer), evaluasi
benchmark/         Pengukuran CPU/RAM/latency (brief bagian F)
deploy/k8s/        Manifest Kubernetes (bonus — brief bagian G)
docs/              Dokumentasi detail (arsitektur, guardrail, model, performa, deployment)
docker-compose.yml Menjalankan ketiga service sekaligus secara lokal
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
| [frontend/README.md](frontend/README.md) | Desain chat UI, keputusan implementasi, cara menjalankan berdiri sendiri |

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
