# Guardrail PII — penjelasan detail

Kode: [`agent/agents/cs_agent/guardrail/`](../agent/agents/cs_agent/guardrail)
Tes: [`agent/tests/`](../agent/tests) (39 unit test + 5 test end-to-end lewat ADK asli)

## 1. Regex (NIK, Email, Telepon)

File: [`regex_detector.py`](../agent/agents/cs_agent/guardrail/regex_detector.py)

Brief memberi tiga regex baseline. Ketiganya punya bug yang membuatnya gagal di kasus
nyata; regex final memperbaikinya (brief eksplisit mengizinkan modifikasi):

| PII | Regex di brief | Masalah | Regex final |
|---|---|---|---|
| NIK | `^[0-9]{16}$` | `^`/`$` membuatnya hanya cocok jika **seluruh pesan** persis 16 digit. Pesan nyata seperti `"NIK saya 3273011506900001"` tidak akan cocok sama sekali → **PII lolos, tidak ada yang diredaksi**. | `(?<![\d])\d(?:[ .\-]?\d){15}(?![\d])` — mencari di dalam kalimat, boleh ada pemisah spasi/titik/strip tiap 4 digit (`3273 0115 0690 0001`), dibatasi word-boundary digit supaya tidak memotong angka yang lebih panjang. |
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+.[a-zA-Z]{2,}` | Titik sebelum TLD tidak di-escape (`.` cocok dengan karakter apa pun), jadi `budi@gmailXcom` pun lolos sebagai email valid — regex jadi longgar tanpa manfaat apa pun. | Titik di-escape (`\.`), plus varian untuk email yang sengaja disamarkan (`nama at gmail dot com`). |
| Telepon | `(+62\|62\|0)8[1-9][0-9]{6,9}` | `+` tidak di-escape di awal grup alternasi → **`re.compile` melempar `re.error`** (grup diawali `+` = "one or more of nothing"). Regex ini tidak bisa dipakai sama sekali. | `+` di-escape, plus dukungan pemisah (`0812-3456-7890`, `+62 812 3456 7890`) dan nomor rumah (`(022) 2501234`). |

Regresi ini diuji eksplisit di [`test_regex.py`](../agent/tests/test_regex.py) — tesnya
membuktikan regex brief gagal, dan regex final berhasil pada kasus yang sama.

**Validasi struktur NIK**: 16 digit yang formatnya salah (provinsi tidak ada di daftar
BPS, tanggal lahir mustahil, dst.) tetap diredaksi (fail-safe — mungkin nomor
kartu/rekening lain), tapi diberi skor lebih rendah untuk observability, bukan ditolak.

**Urutan penting**: NIK dicek sebelum Telepon (`PRIORITY` di `resolve_overlaps`) supaya 16
digit NIK tidak salah kepotong jadi terlihat seperti nomor telepon.

## 2. NER (Nama & Alamat)

Model dilatih sendiri (bukan pretrained NER) — lihat [ner_model.md](ner_model.md) untuk
metodologi dataset, pemilihan arsitektur, dan hasil evaluasi lengkap.

Runtime: [`ner_client.py`](../agent/agents/cs_agent/guardrail/ner_client.py) memanggil
NER Service lewat HTTP dengan:
* **timeout** (default 3s) — guardrail tidak boleh menggantungkan setiap giliran chat
  tanpa batas waktu,
* **retry sekali** untuk error transien (connection reset),
* **circuit breaker** — setelah 3 kegagalan beruntun, berhenti memanggil selama 30 detik
  supaya service yang benar-benar mati tidak membebani setiap pesan dengan biaya timeout
  penuh,
* **cache LRU** — riwayat percakapan dikirim ulang ke LLM tiap giliran; teks yang sudah
  pernah dianalisis tidak perlu dipanggil ulang ke NER Service.

**Filter ketikan acak** ([`redactor.py`](../agent/agents/cs_agent/guardrail/redactor.py)
`plausible_ner_span`): model menandai kata asing yang berdiri sendiri sebagai PERSON dengan
yakin — saat uji langsung, ketikan acak `asmdamwkdmsa` dapat skor 0,988, lalu agent menyapa
pelanggan "Kak asmdamwkdmsa". Span PERSON yang mengandung ≥5 huruf mati berturut-turut kini
ditolak. Batas 5 dipilih dari data: tidak ada satu pun dari 4.745 kata unik di data training
& gold (termasuk semua nama/alamat) yang memenuhinya, sedangkan batas 4 sudah menolak nama
asli seperti *Anggraeni*. Ketikan acak dengan gugus konsonan pendek masih bisa lolos sebagai
nama — arah salah yang aman (disamarkan, bukan dibocorkan).

## 3. Urutan pipeline & data minimisation

```
teks asli
   │
   ▼  1) vault.replace_known()   — PII yang SUDAH diketahui dari giliran sebelumnya
   │                                ditokenkan lagi tanpa perlu NER/regex ulang
   ▼  2) RegexDetector           — NIK, Email, Telepon
   │
   ▼  3) NER Service (HTTP)      — HANYA menerima teks yang sudah bersih dari (2)
   │                                → NER Service secara desain TIDAK PERNAH melihat NIK/
   │                                  email/telepon mentah (data minimisation)
   ▼
teks final ke Gemini
```

Dibuktikan oleh `test_pipeline_and_data_minimisation` di
[`test_vault_redactor.py`](../agent/tests/test_vault_redactor.py): assert eksplisit bahwa
teks yang diterima NER service palsu tidak pernah mengandung NIK/telepon mentah.

## 4. Vault: redaksi yang reversibel

File: [`vault.py`](../agent/agents/cs_agent/guardrail/vault.py)

Brief memberi contoh redaksi statis: `[REDACT_NAMA]`, `[REDACT_ADDRESS]`. Itu didukung
(`PII_REDACTION_MODE=mask`), tapi default sistem ini adalah **pseudonymisation
reversibel**: `[REDACT_NAMA_1]`, `[REDACT_PHONE_1]`, dst., disimpan di *state* sesi (server
side, tidak pernah dikirim ke LLM).

Alasannya: agent customer support **harus bertindak** atas data itu — membuat tiket dengan
nomor telepon asli, mencatat alamat asli untuk survei. Dengan mask statis, begitu nilai
diganti `[REDACT_NAMA]`, nilai aslinya hilang dan tool tidak bisa jalan. Dengan vault:

* nilai yang sama → token yang sama (`Budi` dan `budi ` di kalimat berbeda → token sama),
  supaya model bisa "mengingat" identitas dalam percakapan;
* `before_tool_callback` menukar token → nilai asli **hanya untuk pemanggilan tool itu**
  (LLM tidak pernah melihat nilai asli — argumen yang model tulis di riwayat tetap token);
* `after_model_callback` mengembalikan token pada balasan model menjadi nilai asli
  **milik user itu sendiri**, supaya yang ditampilkan tetap natural ("Baik Kak Budi
  Santoso"), lalu ditokenkan lagi begitu riwayat itu dikirim ke LLM pada giliran
  berikutnya (dibuktikan `test_restored_history_is_retokenised_next_turn`).

## 5. Perilaku saat NER Service down

Dikontrol lewat `PII_FAIL_MODE`:

* **`closed`** (default, direkomendasikan untuk produksi) — Gemini **tidak dipanggil sama
  sekali**; user mendapat pesan bahwa sistem sedang gangguan. Menjamin invariant "tidak ada
  PII mentah yang sampai ke LLM" tidak pernah dilanggar, dengan biaya ketersediaan agent
  saat NER down.
* **`open`** — degradasi ke regex-only (NIK/email/telepon tetap terlindungi, Nama/Alamat
  tidak). Dipilih kalau ketersediaan agent lebih penting daripada proteksi Nama/Alamat
  untuk kasus penggunaan tertentu.

Diuji di `test_fail_closed_when_ner_down` dan `test_fail_open_degrades_to_regex_only`.

## 6. Argumen & hasil tool

Tool bukan hanya teks bebas — argumennya terstruktur (`nama_pelapor`, `kontak`,
`alamat_pemasangan`, ...). `redact_structured()` di
[`redactor.py`](../agent/agents/cs_agent/guardrail/redactor.py) memakai **kebijakan nama
field** (`nama*`, `alamat*`, `email`, `telp*`/`kontak`/`hp` → label PII) ditambah fallback
regex untuk field lain — karena NER butuh konteks kalimat dan tidak cocok dipanggil pada
string pendek semacam `"Budi Santoso"` saja tanpa konteks.

## 7. Apa yang TIDAK dilakukan guardrail ini (batasan yang disadari)

* Tidak mendeteksi PII dalam gambar/lampiran (di luar scope: agent ini hanya menerima
  teks, sesuai brief).
* Tidak mendeteksi entitas selain PERSON/ADDRESS/NIK/EMAIL/PHONE (mis. nomor rekening
  bank, tanggal lahir berdiri sendiri) — bisa ditambah sebagai label NER baru bila
  diperlukan (lihat [ner_model.md](ner_model.md) bagian "Perluasan").
* Vault berada di *session state* in-memory (`InMemorySessionService` untuk demo). Untuk
  produksi nyata, gunakan session service persisten dengan enkripsi at-rest untuk vault
  (nilai PII asli tersimpan di sana selama sesi berlangsung).
