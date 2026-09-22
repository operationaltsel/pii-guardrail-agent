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
    "1122334455": {"nama_pelanggan": "Budi Santoso", "no_hp": "081234567890", "paket": "NusaFiber 50 Mbps",
                   "alamat_pemasangan": "Jl. Sudirman No. 10, Jakarta Pusat", "tagihan": 385000, "status_bayar": "BELUM LUNAS"},
    "2233445566": {"nama_pelanggan": "Siti Rahmawati", "no_hp": "085711223344", "paket": "NusaFiber 100 Mbps",
                   "alamat_pemasangan": "Perum Griya Indah Blok C2 No. 7, Bekasi", "tagihan": 525000, "status_bayar": "LUNAS"},
    "3344556677": {"nama_pelanggan": "I Made Wirawan", "no_hp": "081399887766", "paket": "NusaFiber 30 Mbps",
                   "alamat_pemasangan": "Jl. Raya Kuta No. 88, Badung", "tagihan": 275000, "status_bayar": "BELUM LUNAS"},
}


def _normalize_phone(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return "0" + d[2:] if d.startswith("62") else d


def _find_customer(identitas: str) -> tuple[str, dict] | None:
    """Resolves a customer by whatever the caller actually has on hand: the internal
    10-digit nomor_pelanggan (what a CS system uses), a phone number (what a real customer
    remembers), or a name (last resort, may be ambiguous — first match wins for this demo).
    This mirrors how a real CS lookup works: the agent almost never gets the exact internal
    ID first; it resolves the customer from what they say, then uses the ID internally.
    """
    q_digits = re.sub(r"\D", "", identitas)
    if q_digits in _CUSTOMERS:
        return q_digits, _CUSTOMERS[q_digits]
    if q_digits:
        q_phone = _normalize_phone(identitas)
        for nomor, cust in _CUSTOMERS.items():
            if cust["no_hp"] == q_phone or cust["no_hp"].endswith(q_digits[-8:]) and len(q_digits) >= 8:
                return nomor, cust
    q_name = identitas.strip().lower()
    if len(q_name) >= 3:
        for nomor, cust in _CUSTOMERS.items():
            if q_name in cust["nama_pelanggan"].lower():
                return nomor, cust
    return None
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


def cari_pelanggan(identitas: str) -> dict:
    """Cari data pelanggan NusaTel. Gunakan ini kalau pelanggan TIDAK tahu nomor
    pelanggannya — kebanyakan pelanggan hanya ingat nomor HP atau nama mereka, bukan ID
    internal 10 digit. Coba tool ini dulu dengan nomor HP/nama sebelum meminta pelanggan
    mencari-cari nomor pelanggannya sendiri.

    Args:
        identitas: Nomor pelanggan 10 digit, ATAU nomor HP terdaftar, ATAU nama pelanggan
            (boleh berupa placeholder [REDACT_PHONE_n]/[REDACT_NAMA_n] dari percakapan).
    """
    found = _find_customer(identitas)
    if not found:
        return {"status": "not_found",
                "pesan": "Pelanggan tidak ditemukan dari nomor HP/nama tersebut. Tawarkan untuk "
                         "mencari dengan cara lain, atau minta nomor pelanggan bila pelanggan punya tagihan fisik."}
    nomor, cust = found
    return {"status": "ok", "nomor_pelanggan": nomor, "nama_pelanggan": cust["nama_pelanggan"],
            "no_hp": cust["no_hp"], "paket": cust["paket"], "alamat_pemasangan": cust["alamat_pemasangan"]}


def cek_tagihan(nomor_pelanggan: str) -> dict:
    """Cek tagihan bulan berjalan untuk pelanggan NusaTel.

    Args:
        nomor_pelanggan: Idealnya nomor pelanggan 10 digit (contoh "1122334455"), tapi
            nomor HP terdaftar atau nama pelanggan juga diterima — tool ini akan mencari
            pelanggan yang cocok secara otomatis (sama seperti cari_pelanggan).
    """
    found = _find_customer(nomor_pelanggan)
    if not found:
        return {"status": "error", "pesan": "Nomor pelanggan tidak ditemukan."}
    nomor, cust = found
    return {"status": "ok", "nomor_pelanggan": nomor, "nama_pelanggan": cust["nama_pelanggan"],
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
        nomor_pelanggan: Idealnya nomor pelanggan 10 digit, tapi nomor HP terdaftar atau
            nama pelanggan juga diterima (dicari otomatis, sama seperti cari_pelanggan).
        alamat_baru: Alamat baru lengkap (boleh berupa placeholder [REDACT_ADDRESS_n]).
    """
    found = _find_customer(nomor_pelanggan)
    if not found:
        return {"status": "error", "pesan": "Nomor pelanggan tidak ditemukan."}
    nomor, cust = found
    TOOL_AUDIT.append({"tool": "ubah_alamat_pemasangan", "alamat_baru": alamat_baru})
    cust["alamat_pemasangan_pending"] = alamat_baru
    return {"status": "ok", "nomor_pelanggan": nomor, "pesan": "Pengajuan pindah alamat diterima, survei 1-3 hari kerja.",
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


ALL_TOOLS = [cari_pelanggan, cek_tagihan, cek_gangguan_wilayah, buat_tiket_pengaduan, cek_status_tiket,
            ubah_alamat_pemasangan, cari_faq]
