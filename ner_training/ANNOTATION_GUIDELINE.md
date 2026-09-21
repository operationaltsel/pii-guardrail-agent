# Pedoman Anotasi NER (PERSON & ADDRESS)

Pedoman ini adalah "kontrak" antara data latih, data uji, dan model. Tanpa definisi
yang konsisten, angka akurasi tidak bermakna — model akan dihukum/dihadiahi karena
ambiguitas label, bukan karena kemampuannya.

## Label

| Label     | Placeholder redaksi | Definisi singkat                                   |
|-----------|---------------------|----------------------------------------------------|
| `PERSON`  | `[REDACT_NAMA]`     | Nama diri seseorang (pelanggan, keluarga, pihak lain) |
| `ADDRESS` | `[REDACT_ADDRESS]`  | Alamat yang menunjuk ke lokasi spesifik (tempat tinggal / pengiriman / pemasangan) |

Skema tag token: **BIO** → `O`, `B-PERSON`, `I-PERSON`, `B-ADDRESS`, `I-ADDRESS`.

## PERSON

**Termasuk**
- Nama lengkap maupun sebagian: `Budi`, `Budi Santoso`, `Siti Nur Aisyah`.
- Nama dengan marga / nama adat: `Togar Simanjuntak`, `I Made Wirawan`, `Ni Luh Putu Ayu`.
- Nama dalam huruf kecil / informal: `budi`, `mas joko` → yang dilabeli hanya `joko`.
- Nama orang ketiga (istri, anak, kurir, teknisi) — tetap PII.

**Tidak termasuk (label `O`)**
- Sapaan / gelar di depan nama: `Bapak`, `Ibu`, `Pak`, `Bu`, `Mas`, `Mbak`, `Kak`,
  `Bang`, `Sdr.`, `Tuan`, `Dr.` → `Pak <PERSON>Joko</PERSON>`.
- Nama jalan yang berasal dari nama tokoh **di dalam alamat** → bagian dari `ADDRESS`
  (`Jl. Sudirman` bukan PERSON).
- Nama perusahaan, produk, merek, aplikasi: `Telkomsel`, `IndiHome`, `NusaTel`, `Shopee`.
- Kata umum yang kebetulan bisa menjadi nama bila konteksnya bukan nama:
  `bunga`, `indah`, `fajar`, `jaya`, `rezeki`.

## ADDRESS

Sebuah span dilabeli `ADDRESS` bila **mengandung minimal satu komponen tingkat
jalan/lingkungan**, yaitu salah satu dari:
- jalan / gang / lorong: `Jl.`, `Jln`, `Jalan`, `Gg.`, `Gang`, `Lr.`
- kompleks / perumahan / apartemen / blok: `Perum`, `Komplek`, `Cluster`, `Apartemen`, `Blok C2`
- nomor rumah, `RT/RW`
- desa / kelurahan / dusun

Bila syarat itu terpenuhi, **seluruh rangkaian alamat yang bersambung** ikut dalam span:
kecamatan, kota/kabupaten, provinsi, kode pos, termasuk tanda baca di dalamnya.

```
tinggal di <ADDRESS>Jl. Mawar No. 12 RT 03/RW 05, Kel. Sukajadi, Kota Bandung 40162</ADDRESS>
```

**Tidak termasuk (label `O`)**
- Nama kota/provinsi yang berdiri sendiri: `saya di Bandung`, `ada promo di Jakarta?`
  Alasan: kota tunggal adalah quasi-identifier berisiko rendah; memasukkannya membuat
  label ambigu dan memicu over-redaction pada pertanyaan umum (mis. cek gangguan area).
- Kata "jalan" yang bukan alamat: `jalan-jalan`, `paket masih di jalan`, `jalan tol macet`.
- Kata pengantar: `di`, `ke`, `alamat:`, `tinggal di` tidak ikut span.

## Aturan batas span
- Tanda baca di **ujung** span (`.`, `,`, `;`, `:`) tidak ikut; tanda baca di tengah ikut.
- Dua alamat berbeda dalam satu kalimat → dua span terpisah.
- Nama + alamat bersebelahan tetap dua span (`Budi, Jl. Mawar 5` → PERSON + ADDRESS).

## Mengapa ada pedoman ini
Pada guardrail, **false negative = data bocor ke LLM**, sehingga evaluasi utama kita
adalah *recall* dan *PII leak rate*. Pedoman yang tegas memastikan angka-angka tersebut
mengukur model, bukan ketidakkonsistenan label.
