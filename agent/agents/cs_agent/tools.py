"""Customer-support tools for the fictional ISP/telco "NusaTel" (in-memory mock backend).

Tools receive REAL values (de-tokenised by ``before_tool_callback``) and their outputs are
re-tokenised by ``after_tool_callback`` before the LLM sees them. Field names matter:
``nama_*``, ``alamat*``, ``kontak``, ``email``, ``nik`` are treated as PII (redactor.FIELD_POLICY).
"""
from __future__ import annotations

import itertools
import re
from datetime import date, timedelta

_CUSTOMERS = {
    "1122334455": {"nama_pelanggan": "Budi Santoso", "paket": "NusaFiber 50 Mbps", "alamat_pemasangan":
                   "Jl. Sudirman No. 10, Jakarta Pusat", "tagihan": 385000, "status_bayar": "BELUM LUNAS"},
    "2233445566": {"nama_pelanggan": "Siti Rahmawati", "paket": "NusaFiber 100 Mbps", "alamat_pemasangan":
                   "Perum Griya Indah Blok C2 No. 7, Bekasi", "tagihan": 525000, "status_bayar": "LUNAS"},
    "3344556677": {"nama_pelanggan": "I Made Wirawan", "paket": "NusaFiber 30 Mbps", "alamat_pemasangan":
                   "Jl. Raya Kuta No. 88, Badung", "tagihan": 275000, "status_bayar": "BELUM LUNAS"},
}
_OUTAGES = {
    "bekasi": "Gangguan massal akibat kabel optik putus di area Bekasi Timur. Estimasi normal hari ini 21:00 WIB.",
    "bandung": "Pemeliharaan terjadwal pukul 01:00-04:00 WIB di sebagian wilayah Bandung Utara.",
}
_FAQ = {
    "restart modem": "Matikan modem 30 detik, nyalakan kembali, tunggu lampu PON hijau stabil (±2 menit).",
    "lampu los merah": "Lampu LOS merah berarti sinyal optik terputus. Jangan reset pabrik; laporkan gangguan agar teknisi dikirim.",
    "ganti password wifi": "Buka 192.168.1.1 dari perangkat yang terhubung, login, menu WLAN > Security, ganti WPA key.",
    "pindah alamat": "Pindah alamat dapat diajukan via agent ini. Survei 1-3 hari kerja, biaya Rp150.000.",
    "cara bayar": "Pembayaran via virtual account bank, QRIS, minimarket, atau aplikasi MyNusaTel.",
    "berhenti berlangganan": "Pengajuan berhenti langganan diproses 3 hari kerja; modem wajib dikembalikan.",
}
_TICKETS: dict[str, dict] = {}
_ticket_seq = itertools.count(1001)

# Visible to tests/demo: proves tools received real values while the LLM saw tokens.
TOOL_AUDIT: list[dict] = []


def cek_tagihan(nomor_pelanggan: str) -> dict:
    """Cek tagihan bulan berjalan untuk nomor pelanggan NusaTel (10 digit).

    Args:
        nomor_pelanggan: Nomor pelanggan 10 digit, contoh "1122334455".
    """
    cust = _CUSTOMERS.get(re.sub(r"\D", "", nomor_pelanggan))
    if not cust:
        return {"status": "error", "pesan": "Nomor pelanggan tidak ditemukan."}
    return {"status": "ok", "nomor_pelanggan": nomor_pelanggan, "nama_pelanggan": cust["nama_pelanggan"],
            "paket": cust["paket"], "periode": date.today().strftime("%B %Y"), "total_tagihan": cust["tagihan"],
            "status_bayar": cust["status_bayar"], "jatuh_tempo": (date.today().replace(day=20)).isoformat()}


def cek_gangguan_wilayah(kota: str) -> dict:
    """Cek apakah ada gangguan jaringan atau pemeliharaan di suatu kota.

    Args:
        kota: Nama kota, contoh "Bekasi".
    """
    info = _OUTAGES.get(kota.strip().lower())
    return {"status": "ok", "kota": kota, "ada_gangguan": bool(info), "keterangan": info or "Tidak ada gangguan tercatat."}


def buat_tiket_pengaduan(kategori: str, deskripsi: str, nama_pelapor: str, kontak: str, alamat: str = "") -> dict:
    """Buat tiket pengaduan gangguan/keluhan pelanggan.

    Args:
        kategori: Salah satu dari "internet", "tagihan", "modem", "layanan", "lainnya".
        deskripsi: Ringkasan keluhan pelanggan.
        nama_pelapor: Nama pelapor (boleh berupa placeholder [REDACT_NAMA_n] dari percakapan).
        kontak: Nomor telepon atau email pelapor (boleh berupa placeholder [REDACT_PHONE_n]/[REDACT_EMAIL_n]).
        alamat: Alamat lokasi gangguan bila relevan (boleh berupa placeholder [REDACT_ADDRESS_n]).
    """
    ticket_id = f"TKT-{next(_ticket_seq)}"
    _TICKETS[ticket_id] = {"kategori": kategori, "deskripsi": deskripsi, "nama_pelapor": nama_pelapor,
                           "kontak": kontak, "alamat": alamat, "status": "DIBUKA",
                           "estimasi": (date.today() + timedelta(days=1)).isoformat()}
    TOOL_AUDIT.append({"tool": "buat_tiket_pengaduan", "nama_pelapor": nama_pelapor, "kontak": kontak, "alamat": alamat})
    return {"status": "ok", "nomor_tiket": ticket_id, "status_tiket": "DIBUKA",
            "estimasi_penanganan": _TICKETS[ticket_id]["estimasi"],
            "catatan": "Teknisi akan menghubungi pelapor melalui kontak yang terdaftar."}


def cek_status_tiket(nomor_tiket: str) -> dict:
    """Cek status tiket pengaduan.

    Args:
        nomor_tiket: Nomor tiket, contoh "TKT-1001".
    """
    t = _TICKETS.get(nomor_tiket.strip().upper())
    if not t:
        return {"status": "error", "pesan": "Tiket tidak ditemukan."}
    return {"status": "ok", "nomor_tiket": nomor_tiket, "kategori": t["kategori"], "status_tiket": t["status"],
            "estimasi_penanganan": t["estimasi"], "nama_pelapor": t["nama_pelapor"]}


def ubah_alamat_pemasangan(nomor_pelanggan: str, alamat_baru: str) -> dict:
    """Ajukan perubahan alamat pemasangan layanan.

    Args:
        nomor_pelanggan: Nomor pelanggan 10 digit.
        alamat_baru: Alamat baru lengkap (boleh berupa placeholder [REDACT_ADDRESS_n]).
    """
    cust = _CUSTOMERS.get(re.sub(r"\D", "", nomor_pelanggan))
    if not cust:
        return {"status": "error", "pesan": "Nomor pelanggan tidak ditemukan."}
    TOOL_AUDIT.append({"tool": "ubah_alamat_pemasangan", "alamat_baru": alamat_baru})
    cust["alamat_pemasangan_pending"] = alamat_baru
    return {"status": "ok", "pesan": "Pengajuan pindah alamat diterima, survei 1-3 hari kerja.",
            "alamat_baru": alamat_baru, "biaya": 150000}


def cari_faq(topik: str) -> dict:
    """Cari jawaban dari basis pengetahuan (FAQ) NusaTel.

    Args:
        topik: Kata kunci, contoh "restart modem", "lampu LOS merah", "cara bayar".
    """
    q = set(re.findall(r"\w+", topik.lower()))
    scored = sorted(((len(q & set(k.split())), k) for k in _FAQ), reverse=True)
    hits = [{"topik": k, "jawaban": _FAQ[k]} for s, k in scored if s > 0][:2]
    return {"status": "ok", "hasil": hits or [{"topik": "-", "jawaban": "Tidak ditemukan di FAQ."}]}


ALL_TOOLS = [cek_tagihan, cek_gangguan_wilayah, buat_tiket_pengaduan, cek_status_tiket, ubah_alamat_pemasangan, cari_faq]
