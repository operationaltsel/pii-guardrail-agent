# Model NER — metodologi & evaluasi

Kode: [`ner_training/`](../ner_training) · Model yang dipakai layanan:
[`ner_service/model/`](../ner_service/model)

## 1. Kenapa harus melatih sendiri, dan apa artinya "melatih sendiri" di sini

Brief mensyaratkan model NER buatan sendiri, bukan model NER siap-pakai. Pendekatan di
sini adalah **fine-tuning** encoder Bahasa Indonesia pretrained
([IndoBERT](https://huggingface.co/indobenchmark), dilatih Language Model — **bukan**
NER) dengan *classification head* baru, dataset berlabel PERSON/ADDRESS buatan sendiri,
dan skema label kita sendiri. IndoBERT tidak tahu apa itu "PERSON" atau "ADDRESS" sebelum
fine-tuning ini — kepala klasifikasi, data, dan keputusan threshold semuanya milik proyek
ini. Ini dibandingkan dengan baseline CRF yang dilatih murni dari nol (fitur tangan +
`sklearn-crfsuite`), untuk mengukur trade-off, bukan untuk menyembunyikan bahwa fine-tuning
dipakai.

## 2. Dataset

### 2.1 Anotasi

Skema label & aturan batas span didefinisikan eksplisit di
[`ANNOTATION_GUIDELINE.md`](../ner_training/ANNOTATION_GUIDELINE.md) — poin pentingnya:

* **PERSON** tidak termasuk sapaan (`Bapak`, `Kak`, ...) dan tidak termasuk nama
  perusahaan/produk.
* **ADDRESS** harus mengandung minimal satu komponen tingkat jalan/RT-RW/kompleks; nama
  kota saja **tidak** dianggap ADDRESS (mengurangi over-redaction pada pertanyaan umum
  seperti "ada gangguan di Bandung?").
* Prioritas metrik adalah **recall** (kebocoran PII jauh lebih mahal daripada redaksi
  berlebih) — lihat bagian 4.

### 2.2 Data latih & dev: sintetis, dari template + leksikon

[`generate_dataset.py`](../ner_training/src/generate_dataset.py) menyusun kalimat dari:
* **246 template** kalimat customer-support (formal, informal/chat, form terstruktur,
  campuran PII, negatif) untuk train; **47 template terpisah** untuk dev (frasa yang
  belum pernah dilihat model saat training, mengukur generalisasi bukan hafalan template).
* **Leksikon**: 250+ nama depan, 180+ nama belakang (Jawa, Sunda, Batak, Minang, Bugis,
  Bali, Tionghoa-Indonesia, Arab-Indonesia, dll — lihat
  [`data/lexicon/`](../ner_training/data/lexicon)), 190+ nama jalan (termasuk nama jalan
  dari nama tokoh, supaya model belajar "Jl. Sudirman" = ADDRESS bukan PERSON), 100 nama
  kompleks/perumahan, dan ~500 kelurahan/kecamatan.
* **Hard negatives** sengaja disisipkan: kata yang bisa jadi nama tapi sering bukan
  (`Bunga`, `Indah`, `Fajar`, `Jaya`), "jalan" yang bukan alamat (`jalan-jalan`, `paket
  masih di jalan`), kota berdiri sendiri, nama produk yang mirip nama orang (`paket
  Surya`, `paket Bintang`).
* Variasi gaya: huruf kecil, singkatan chat (`sy`, `yg`, `tdk`, `udah`), placeholder
  `[REDACT_*]` yang sudah ada dari giliran sebelumnya (diuji harus **diabaikan**, tidak
  dianggap entity baru), pesan panjang multi-kalimat dengan entity di posisi mana pun
  termasuk paling akhir.

### 2.3 Kontrol kebocoran data (leakage)

Ini bagian yang paling menentukan apakah angka evaluasi bisa dipercaya:

* **Train vs dev pakai template yang berbeda sama sekali** (disjoint), bukan split acak
  dari kumpulan template yang sama.
* **Setiap token pembeda yang muncul di gold test set (nama, jalan, kelurahan) dibuang
  dari leksikon train *dan* dev** ([`lexicon.py`](../ner_training/src/lexicon.py),
  fungsi `build_pools(exclude_gold=True)`) — supaya gold test set murni mengukur
  generalisasi ke nama/alamat yang **belum pernah dilihat model**, bukan hafalan.
  Partikel nama umum (`Muhammad`, `Siti`, `I`, `Made`, ...) dan kata alamat generik
  (`Jl.`, `RT`, `Indah`, ...) dikecualikan dari aturan ini — membuangnya tidak realistis.
* Kota/provinsi adalah himpunan tertutup (~514 kabupaten/kota) sehingga boleh tumpang
  tindih antar split — ini bukan sumber kebocoran karena himpunannya memang terbatas dan
  publik.

### 2.4 Gold test set — ditulis tangan, terpisah total dari generator

[`data/gold/test_gold.txt`](../ner_training/data/gold/test_gold.txt): **135 kalimat**
ditulis manual (bukan dari template generator), dikelompokkan per kategori
(`formal`, `informal`, `form`, `multi_entity`, `hard_names`, `hard_address`, `negative`,
`mixed_pii`) — melebihi minimal 10 kalimat yang diminta brief, karena dengan hanya 10
kalimat satu kesalahan saja mengubah skor 10 poin persentase. Berisi 76 entity PERSON, 52
ADDRESS, plus NIK/EMAIL/PHONE untuk uji guardrail regex end-to-end.

## 3. Arsitektur & pilihan model

| Model | Params | Deskripsi |
|---|---|---|
| **CRF** (baseline) | — | `sklearn-crfsuite`, fitur tangan (bentuk kata, awalan/akhiran, kata kunci alamat/nama di sekitar token, kapitalisasi) |
| **IndoBERT-lite** (dipakai layanan) | 11.1M | Fine-tune `indobenchmark/indobert-lite-base-p1` (ALBERT, parameter dibagi antar layer → checkpoint kecil) |
| **IndoBERT-base** (pembanding) | 124.4M | Fine-tune `indobenchmark/indobert-base-p1` (BERT-base standar) |

Loop training kustom (bukan `Trainer` HF) di
[`train_transformer.py`](../ner_training/src/train_transformer.py) — AdamW dengan warmup
linear, gradient clipping, *length-bucketed batching* (mengelompokkan kalimat sepanjang
mirip per batch supaya padding minimal → epoch lebih cepat di CPU), early stopping pada
F1 dev.

**Threshold keputusan** entity (`1 - P(O) >= threshold`) di-tuning khusus di data dev
untuk **memaksimalkan F2** (recall dibobot 2x) dengan syarat precision ≥ 0.90 — lihat
[`tune_threshold.py`](../ner_training/src/tune_threshold.py) dan alasannya di bagian 4.

## 4. Metrik: kenapa recall diutamakan

Untuk guardrail PII, dua jenis kesalahan berdampak sangat berbeda:

* **False negative** (PII lolos ke Gemini) = **kebocoran data**. Ini kegagalan utama.
* **False positive** (kata biasa ikut diredaksi) = jawaban agent kurang pas, tapi tidak
  membocorkan apa pun.

[`metrics.py`](../ner_training/src/metrics.py) melaporkan tiga sudut pandang pelengkap:

1. **strict** — F1 span-level exact match (standar NER).
2. **lenient** — dihitung "ketemu" bila span prediksi overlap dengan gold pada label yang
   sama — mis. `"Jl. Mawar No. 5"` vs `"Jl. Mawar No. 5 Bandung"` tetap dianggap berhasil
   karena PII inti sudah tertutup.
3. **char-level, tidak bergantung label** — metrik yang sebenarnya jadi tujuan guardrail:
   * `leak_rate` — persentase karakter PII gold yang **tidak** tertutup prediksi apa pun
     (target: sekecil mungkin)
   * `over_redaction` — persentase karakter non-PII yang ikut diredaksi
   * `clean_message_rate` — persentase pesan yang PII-nya tertutup 100%

## 5. Hasil

Angka final, direproduksi dengan `make evaluate-crf && make evaluate-model` (lite) dan
`evaluate.py --model ner_training/models/indobert-base-onnx-int8 --name indobert-base`
(base). JSON lengkap + `*_errors.md` (setiap kesalahan pada gold set) ada di
[`ner_training/reports/`](../ner_training/reports).

| Model | Params | Dev strict F1 | Gold strict F1 | Gold lenient F1 | Gold leak rate | Gold recall PERSON / ADDRESS |
|---|---|---|---|---|---|---|
| CRF | — | 0.873 | 0.864 | 0.952 | 1.97% | 0.789 / 0.923 |
| **IndoBERT-lite** (dipakai layanan) | 11.1M | 0.976 | **0.984** | 0.992 | **0.20%** | 0.987 / 0.981 |
| IndoBERT-base (pembanding) | 123.9M | 0.984 | 0.977 | 0.992 | 0.20% | 0.974 / 0.981 |

Kedua model transformer jauh melampaui CRF di setiap sudut pandang metrik, dan
menurunkan leak rate dari ~2% ke ~0,2% — pada 135 kalimat gold (2.544 karakter PII),
itu artinya CRF membiarkan ~50 karakter PII lolos, sedangkan kedua model transformer
hanya ~5 karakter (lihat detail di bawah).

**Yang menarik:** pada gold test set (satu-satunya data yang benar-benar *held-out*,
lihat § 2.3), IndoBERT-**lite** justru sedikit mengungguli IndoBERT-**base**
(F1 0,984 vs 0,977), walau base menang tipis di data dev. Dengan gold set sekecil 135
kalimat, selisih ini (2 kesalahan) tidak dapat diklaim signifikan secara statistik —
kesimpulan yang jujur adalah **kedua ukuran model sama-sama sanggup menyelesaikan tugas
ini**, bukan bahwa model kecil "lebih baik" secara umum.

**Error analysis (gold set):** IndoBERT-lite salah pada **3 dari 135** kalimat:
1. `"Fajar di sini... sejak fajar tadi"` — nama depan tunggal yang persis sama dengan
   kata umum ("fajar" = dawn) dipakai dua kali dalam satu kalimat sebagai nama **dan**
   sebagai kata biasa. Ini kasus paling ambigu yang sengaja dimasukkan ke gold set.
2. Batas span ADDRESS kelebihan satu kata ("desa," ikut tertangkap sebelum "Desa Tanjung
   Sari...") — PII inti tetap tertutup penuh (leak 0%), murni kelonggaran batas.
3. Email tersamar (`"andi.wijaya at gmail dot com"`) salah dilabeli PERSON oleh NER.
   **Tidak berdampak pada guardrail sesungguhnya**: di pipeline nyata, regex mendeteksi
   dan meredaksi email ini *sebelum* teks sampai ke NER (lihat [guardrail.md § 3](guardrail.md#3-urutan-pipeline--data-minimisation));
   kegagalan ini hanya muncul saat NER dievaluasi berdiri sendiri di luar pipeline.

IndoBERT-base salah pada 4/135 kalimat (kesalahan serupa, ditambah satu batas span
PERSON yang kelebihan kata "anaknya"). Detail lengkap dengan setiap contoh kalimat:
[`indobert-lite_errors.md`](../ner_training/reports/indobert-lite_errors.md),
[`indobert-base_errors.md`](../ner_training/reports/indobert-base_errors.md).

## 6. Model yang dipilih untuk layanan

**IndoBERT-lite** ([`ner_service/model/`](../ner_service/model)) — berdasarkan data,
bukan asumsi "model kecil pasti lebih murah":

| Kriteria | IndoBERT-lite | IndoBERT-base | Selisih |
|---|---|---|---|
| Ukuran model (int8 ONNX) | 38,1 MB | 119,3 MB | lite 3,1× lebih kecil |
| RAM setelah dimuat | 77,6 MB | 162,4 MB | lite 2,1× lebih hemat |
| Gold F1 (strict) | **0,984** | 0,977 | lite unggul tipis |
| Leak rate | 0,20% | 0,20% | setara |
| Latency p50 / p95 | 24,7 / 52,6 ms | 12,1 / 26,9 ms | base lebih cepat (lihat catatan) |

Lite menang di ukuran, RAM, dan akurasi gold; base menang di latency pada benchmark ini.
**Catatan latency**: hasil ini kontra-intuitif secara arsitektur — ALBERT (basis lite)
berbagi bobot antar layer sehingga file model kecil, tapi tetap menjalankan komputasi
sebanyak 12 layer per forward pass (FLOPs per inferensi mirip dengan base, bukan lebih
kecil), ditambah operasi ekstra untuk factorized embedding yang tidak selalu
teroptimasi sama baiknya oleh ONNX Runtime int8 dibanding graph BERT standar. Detail
pengukuran (metodologi, kondisi CPU) ada di [performance.md](performance.md); di sana
juga didokumentasikan bahwa jika latency menjadi prioritas utama, base adalah alternatif
yang valid dengan RAM 2× lebih besar.

**Keputusan**: untuk beban kerja guardrail ini (PERSON/ADDRESS, domain customer support
yang relatif sempit), 11,1M parameter sudah cukup — menambah 11× parameter (base) tidak
memberi keunggulan akurasi yang jelas di data held-out, sementara RAM yang dibutuhkan
berlipat. Sesuai filosofi *"tidak dituntut akurasi tinggi, tapi tetap dioptimalkan
serius"*: kami memilih model yang paling hemat sumber daya *di antara yang akurasinya
setara*, bukan model yang akurasinya "sedikit lebih tinggi di satu metrik" dengan biaya
RAM dua kali lipat.

## 7. Perluasan

Menambah entity baru (mis. nomor rekening, tanggal lahir) berarti: (1) tambah label di
`annotation.py::LABELS`, (2) tambah pola generator/leksikon relevan, (3) tambah aturan di
`ANNOTATION_GUIDELINE.md`, (4) retrain. Arsitektur token-classification yang dipakai di
sini generik untuk sequence labeling apa pun, tidak spesifik PERSON/ADDRESS.
