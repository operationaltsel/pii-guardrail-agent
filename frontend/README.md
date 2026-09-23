# Ventra Care — Chat UI

Antarmuka chat customer-facing untuk agent Ventra, menggantikan konsol developer bawaan
ADK (`adk web`) yang tidak dirancang untuk dilihat pelanggan. Satu file HTML statis, tanpa
langkah build — memudahkan deploy (Nginx/`python -m http.server`/CDN mana pun) dan
memastikan tidak ada dependency Node.js yang perlu dijaga.

## Menjalankan

Bagian dari `docker compose up --build` di root repo (lihat [README](../README.md)) — buka
**http://localhost:3100**.

Berdiri sendiri (development):
```bash
# terminal 1
cd ner_service && uvicorn app.main:app --port 8001
# terminal 2
cd agent && adk api_server agents --port 8000 --allow_origins http://localhost:3100
# terminal 3
cd frontend && python -m http.server 3100
```

Untuk menunjuk ke API di alamat lain (mis. staging): buka
`http://localhost:3100/?api=https://staging.example.com`, atau set
`window.VENTRA_API_BASE` sebelum skrip dimuat.

## Keputusan desain

* **Terasa seperti asisten AI sungguhan, bukan widget customer-support**: iterasi pertama
  memakai kartu melayang (border-radius + shadow) di atas backdrop abu-abu, ikon gradien,
  dan banner warna hijau permanen — pola umum "template produk AI" yang generik. Diubah ke
  shell full-bleed tanpa kartu, satu warna aksen datar tanpa gradient, dan balasan asisten
  **tanpa bubble** (teks polos + avatar kecil) — pola yang sama dipakai ChatGPT/Claude, dan
  jadi sinyal visual terkuat bahwa ini asisten AI, bukan widget chat yang ditempel di situs.
  Design system awal dihasilkan lewat skill `ui-ux-pro-max` (query: *"customer support chat
  telco enterprise trust"*), lalu disederhanakan lebih jauh sesuai arahan di atas.
* **Tanpa framework**: HTML/CSS/JS vanilla. Untuk satu halaman chat dengan kompleksitas
  state yang moderat, ini lebih ringan dan lebih mudah diaudit daripada menambah toolchain
  React/build step ke sebuah take-home project.
* **Terhubung langsung ke REST API ADK** (`/apps/.../sessions`, `/run_sse`) — bukan lewat
  backend perantara tambahan. Endpoint dan skema field (`content.parts[].functionCall`,
  `actions.stateDelta`, camelCase JSON) diverifikasi langsung dari source ADK
  (`google/adk/cli/api_server.py`), bukan ditebak.
* **Markdown minimal & aman**: balasan model (berisi `**bold**`, list bernomor) di-escape
  HTML dulu, baru diterapkan allow-list transform terbatas — tidak pernah menyisipkan HTML
  mentah dari model/user ke DOM.
* **Bukti guardrail nyata, ditempel di tempat kejadian**: setiap pesan pengguna yang
  memicu redaksi mendapat catatan kecil di bawahnya (mis. "1 telepon, 1 nama disamarkan
  sebelum diproses AI"), diambil dari `actions.stateDelta.pii_report` yang ditulis
  `before_model_callback` — nilai sungguhan dari server, bukan animasi kosong. Awalnya ini
  hanya berupa strip banner di header; diubah setelah pengujian langsung menunjukkan mode
  `pseudonymize` mengembalikan nilai asli pengguna ke balasan yang ditampilkan (by design,
  supaya bot tetap bisa menyebut data pelanggan), sehingga pesan bot yang mengutip ulang
  nomor/nama pengguna terlihat seperti "redaksi tidak terjadi" padahal Gemini tidak pernah
  menerima nilai mentahnya (dibuktikan lewat reproduksi langsung ke API:
  `pii_report.detected: {"PHONE": 1}`). Menempelkan buktinya tepat di pesan yang memicunya
  jauh lebih sulit terlewat daripada banner sesaat di bagian lain halaman.
  *(Catatan implementasi: kunci `pii_report` sengaja TIDAK diberi prefiks `temp:` — ADK
  menghapus key berprefiks itu dari `state_delta` sebelum event di-stream ke client, lihat
  `base_session_service.py::_trim_temp_delta_state`. Ditemukan & diverifikasi langsung dari
  source ADK saat frontend ini diuji hidup.)*
* **Indikator tool-call**: panggilan tool (`cek_tagihan`, `buat_tiket_pengaduan`, dst.)
  ditampilkan sebagai chip berlabel Bahasa Indonesia yang ramah, bukan nama fungsi mentah —
  transparansi tanpa membocorkan detail implementasi ke pengguna awam.
* **Penanganan error yang informatif**: error 503 "model sedang sibuk" dari Gemini (dialami
  langsung saat pengujian) diterjemahkan jadi pesan yang jelas + tombol "Coba lagi", alih-alih
  membiarkan pengguna melihat JSON error mentah seperti default konsol ADK.
* **Resilien terhadap restart server**: session ID divalidasi (`GET` sebelum dipakai) setiap
  kali; jika server di-restart (session in-memory hilang), frontend otomatis membuat sesi
  baru alih-alih gagal diam-diam.
* **Satu percakapan berkelanjutan, tanpa sidebar riwayat**: sempat ada sidebar daftar sesi
  ala ChatGPT/Claude, tapi dilepas lagi — untuk widget CS setransaksional ini (gaya Veronika
  Telkomsel: to-the-point, sekali sesi selesai) daftar riwayat percakapan lama tidak
  menambah nilai dan cuma menambah kompleksitas. Sesi tetap satu ID persisten per pengguna
  (bertahan lintas refresh via `localStorage`), cuma tidak ada UI untuk menjelajah sesi lain.
* **Balasan singkat & tombol pilihan cepat (gaya asisten telco seperti Veronika)**: prompt
  agent diarahkan menutup giliran dengan pilihan tertutup yang jelas (mis. konfirmasi ya/tidak,
  menu kategori, lanjutan tindakan) sebagai baris `[PILIHAN] Opsi 1 | Opsi 2 | ...` di akhir
  pesan. Frontend mem-parsing baris itu, menghapusnya dari teks yang tampil, dan merender
  tiap opsi sebagai chip yang bisa langsung diklik (mengirim label opsi itu sebagai pesan
  berikutnya) — mengurangi mengetik untuk alur transaksional umum, tanpa membatasi pelanggan
  yang tetap mau mengetik bebas.
* **Aksesibilitas**: kontras warna diverifikasi (≥4.5:1 teks normal), navigasi keyboard penuh
  dengan focus ring terlihat, `role="log" aria-live="polite"` pada transkrip agar pembaca
  layar mengumumkan balasan baru, target sentuh minimal 44×44px, `prefers-reduced-motion`
  dihormati.
* **Responsif**: diuji 375px (mobile) sampai desktop lebar, tanpa scroll horizontal di titik
  mana pun.
