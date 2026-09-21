# Contoh input–output guardrail

Semua contoh di bawah adalah kasus nyata yang tercakup oleh test suite
([`agent/tests/`](../agent/tests), [`ner_training/data/gold/test_gold.txt`](../ner_training/data/gold/test_gold.txt))
— bukan ilustrasi yang tidak diverifikasi.

## 1. Contoh persis dari brief

**Mode `mask`** (`PII_REDACTION_MODE=mask`, sesuai format di brief):

```
Input : Nama saya Budi, saya tinggal di Jl.ABC
Output: Nama saya [REDACT_NAMA], saya tinggal di [REDACT_ADDRESS]
```
Test: `test_brief_example` di [`test_vault_redactor.py`](../agent/tests/test_vault_redactor.py).

## 2. Regex — ketiga jenis PII terstruktur, satu kalimat

```
Input : Saya Dian, NIK 3171234501900001, HP +62 812-3456-7890, email dian@yahoo.co.id
```

Urutan pipeline: NIK dideteksi & diredaksi dulu (prioritas tertinggi, supaya 16 digitnya
tidak salah kepotong jadi terbaca sebagai bagian nomor telepon), lalu Telepon, lalu Email:

```
Output (mode pseudonymize): Saya [REDACT_NAMA_1], NIK [REDACT_NIK_1], HP [REDACT_PHONE_1], email [REDACT_EMAIL_1]
```
Test: `test_multiple_and_priority`, `test_pipeline_and_data_minimisation`.

## 3. NER — nama & alamat informal, tanpa regex sama sekali

```
Input : halo min sy rizky ramadhan, wifi dirumah mati terus nih
Output: halo min sy [REDACT_NAMA_1], wifi dirumah mati terus nih

Input : kak paketnya kirim ke jl melati no 5 bekasi ya
Output: kak paketnya kirim ke [REDACT_ADDRESS_1] ya
```
Sumber: kategori `informal` di gold test set — lihat
`ner_training/reports/<model>_errors.md` untuk kasus yang berhasil vs gagal.

## 4. Data minimisation — NER Service tidak pernah melihat NIK/telepon mentah

```
Input mentah         : Saya Budi Santoso, NIK 3273011506900001, HP 0812-3456-7890,
                        tinggal di Jl. Mawar No. 5, Bandung
Dikirim ke NER Service: Saya Budi Santoso, NIK [REDACT_NIK_1], HP [REDACT_PHONE_1],
                        tinggal di Jl. Mawar No. 5, Bandung
Dikirim ke Gemini     : Saya [REDACT_NAMA_1], NIK [REDACT_NIK_1], HP [REDACT_PHONE_1],
                        tinggal di [REDACT_ADDRESS_1]
```
Test: `test_pipeline_and_data_minimisation` — assert eksplisit bahwa teks yang diterima
NER service (lewat client palsu yang merekam input) tidak pernah mengandung NIK/telepon
mentah.

## 5. Percakapan multi-giliran dengan tool call (skenario lengkap)

Ini yang membuktikan guardrail bekerja **menyeluruh**, bukan cuma di pesan pertama:

**Giliran 1 — user melapor gangguan:**
```
User → Agent : Halo, saya Budi Santoso, NIK 3273011506900001, HP 0812-3456-7890,
                email budi@gmail.com. Internet di Jl. Mawar No. 5, Bandung mati.
Agent → Gemini (setelah guardrail):
                Halo, saya [REDACT_NAMA_1], NIK [REDACT_NIK_1], HP [REDACT_PHONE_1],
                email [REDACT_EMAIL_1]. Internet di [REDACT_ADDRESS_1] mati.
```

**Giliran 2 — user minta dibuatkan tiket:**
```
User → Agent : Tolong buatkan tiket ya
Gemini memanggil tool buat_tiket_pengaduan(
    nama_pelapor="[REDACT_NAMA_1]", kontak="[REDACT_PHONE_1]", alamat="[REDACT_ADDRESS_1]")
→ before_tool_callback menukar token ke nilai ASLI sebelum tool dijalankan →
  tool benar-benar menerima "Budi Santoso" / "0812-3456-7890" / "Jl. Mawar No. 5, Bandung"
  dan bisa membuat tiket TKT-1001 yang valid.
→ after_tool_callback meredaksi lagi hasil tool sebelum masuk riwayat model:
  {"nomor_tiket": "TKT-1001", "nama_pelapor": "[REDACT_NAMA_1]", ...}
Gemini → Agent: "Baik Kak [REDACT_NAMA_1], tiket TKT-1001 sudah dibuat. Teknisi akan
                 menghubungi [REDACT_PHONE_1]."
Agent → User  : "Baik Kak Budi Santoso, tiket TKT-1001 sudah dibuat. Teknisi akan
                 menghubungi 0812-3456-7890."
```

Poin penting: **nilai PII mentah tidak pernah muncul di satu pun request yang dikirim ke
Gemini** — termasuk saat riwayat giliran 1 (yang sudah direstorasi jadi teks natural untuk
user di langkah terakhir) dikirim ulang ke Gemini pada giliran 3, ia sudah ditokenkan
ulang oleh vault sebelum keluar dari `before_model_callback`.

Test: `test_no_raw_pii_reaches_llm_and_tool_gets_real_values` dan
`test_restored_history_is_retokenised_next_turn` di
[`test_agent_e2e.py`](../agent/tests/test_agent_e2e.py) — dijalankan lewat
`InMemoryRunner` ADK **asli** (bukan simulasi), dengan LLM palsu yang merekam **setiap**
`LlmRequest` mentah untuk diperiksa.

## 6. NER Service tidak bisa dihubungi

**`PII_FAIL_MODE=closed`** (default):
```
User → Agent : Nama saya Budi Santoso
Agent → User : "Mohon maaf, sistem perlindungan data kami sedang mengalami gangguan
                sehingga pesan Anda belum dapat diproses dengan aman. Silakan coba lagi
                dalam beberapa saat. Data pribadi Anda tidak dikirim ke mana pun."
```
Gemini **tidak dipanggil sama sekali** — test `test_fail_closed_when_ner_down` membuktikan
`REQUESTS` (daftar semua request ke LLM) tetap kosong.

**`PII_FAIL_MODE=open`** (agent tetap jalan, degradasi ke regex-only):
```
User → Agent : NIK 3273011506900001, nama Budi
Agent → Gemini: NIK [REDACT_NIK_1], nama Budi   ← NIK tetap terlindungi, "Budi" tidak
                                                    (NER-nya yang mati)
```

## 7. Kasus negatif — tidak over-redaksi pertanyaan umum

```
Input : Saya mau jalan-jalan ke Bali bulan depan, apakah roaming aktif otomatis?
Output: (tidak ada perubahan — "jalan-jalan" dan "Bali" bukan PII)

Input : Apakah ada gangguan jaringan di Surabaya hari ini?
Output: (tidak ada perubahan — nama kota berdiri sendiri bukan ADDRESS, lihat
         ANNOTATION_GUIDELINE.md)
```
Kategori `negative` di gold test set berisi 30 kalimat seperti ini, khusus untuk mengukur
`over_redaction` (lihat [ner_model.md](ner_model.md) § 4).
