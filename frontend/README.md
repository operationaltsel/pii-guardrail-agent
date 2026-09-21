# NusaTel Care — Chat UI

Antarmuka chat customer-facing untuk agent NusaTel, menggantikan konsol developer bawaan
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
`window.NUSATEL_API_BASE` sebelum skrip dimuat.

## Keputusan desain

* **Design system**: dihasilkan lewat skill `ui-ux-pro-max` (query: *"customer support chat
  telco enterprise trust"*) → Swiss/Minimalism, warna trust-blue (`#2563EB`), tipografi
  Lexend + Source Sans 3 — cocok untuk produk enterprise/customer-support, mendukung
  light & dark mode.
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
* **Bukti guardrail nyata, bukan dekoratif**: strip kepercayaan di header menampilkan
  jumlah data pribadi yang baru disamarkan, diambil dari `actions.stateDelta.pii_report`
  yang ditulis `before_model_callback` — nilai sungguhan dari server, bukan animasi kosong.
  *(Catatan implementasi: kunci ini sengaja TIDAK diberi prefiks `temp:` — ADK menghapus
  key berprefiks itu dari `state_delta` sebelum event di-stream ke client, lihat
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
* **Aksesibilitas**: kontras warna diverifikasi (≥4.5:1 teks normal), navigasi keyboard penuh
  dengan focus ring terlihat, `role="log" aria-live="polite"` pada transkrip agar pembaca
  layar mengumumkan balasan baru, target sentuh minimal 44×44px, `prefers-reduced-motion`
  dihormati.
* **Responsif**: diuji 375px (mobile) sampai desktop lebar, tanpa scroll horizontal di titik
  mana pun.
