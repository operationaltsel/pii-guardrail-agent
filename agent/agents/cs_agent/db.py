"""SQLite-backed persistence for the mock Ventra backend (customers, tickets).

A real ISP would call an existing CRM/billing API here; this file exists only so the demo's
customer/ticket data survives a container restart instead of resetting every time, without
pulling in a full database service for what is still explicitly a fictional backend (see
tools.py). FAQ/outage reference data stays a plain dict in tools.py — it's static lookup
content, not records that get created or mutated.

Each call opens and closes its own connection: tool calls may run off the main event loop
(ADK) and sqlite3 connections aren't safe to share across threads, so a fresh connection per
call is simpler and safer than pooling for a handful of rows.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "ventra.db"

_SEED_CUSTOMERS = [
    ("1122334455", "Budi Santoso", "081234567890", "VentraFiber 50 Mbps",
     "Jl. Sudirman No. 10, Jakarta Pusat", None, 385000, "BELUM LUNAS"),
    ("2233445566", "Siti Rahmawati", "085711223344", "VentraFiber 100 Mbps",
     "Perum Griya Indah Blok C2 No. 7, Bekasi", None, 525000, "LUNAS"),
    ("3344556677", "I Made Wirawan", "081399887766", "VentraFiber 30 Mbps",
     "Jl. Raya Kuta No. 88, Badung", None, 275000, "BELUM LUNAS"),
]


def _db_path() -> str:
    return os.getenv("VENTRA_DB_PATH") or str(_DEFAULT_PATH)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS customers (
            nomor_pelanggan TEXT PRIMARY KEY,
            nama_pelanggan TEXT NOT NULL,
            no_hp TEXT NOT NULL,
            paket TEXT NOT NULL,
            alamat_pemasangan TEXT NOT NULL,
            alamat_pemasangan_pending TEXT,
            tagihan INTEGER NOT NULL,
            status_bayar TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tickets (
            nomor_tiket TEXT PRIMARY KEY,
            kategori TEXT NOT NULL,
            deskripsi TEXT NOT NULL,
            nama_pelapor TEXT NOT NULL,
            kontak TEXT NOT NULL,
            alamat TEXT,
            status TEXT NOT NULL,
            estimasi TEXT NOT NULL,
            dibuat_pada TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO customers (nomor_pelanggan, nama_pelanggan, no_hp, paket, "
            "alamat_pemasangan, alamat_pemasangan_pending, tagihan, status_bayar) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            _SEED_CUSTOMERS,
        )


@contextmanager
def _connect():
    path = _db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def all_customers() -> list[dict]:
    with _connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM customers")]


def set_pending_address(nomor_pelanggan: str, alamat_baru: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE customers SET alamat_pemasangan_pending = ? WHERE nomor_pelanggan = ?",
            (alamat_baru, nomor_pelanggan),
        )


def create_ticket(kategori: str, deskripsi: str, nama_pelapor: str, kontak: str, alamat: str,
                   status: str, estimasi: str) -> str:
    """Inserts a new ticket and returns its generated TKT-#### id.

    The next number is derived from existing rows (not an in-memory counter) so numbering
    survives restarts; computing it in the same transaction as the insert avoids a race
    between two tickets picking the same number.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(nomor_tiket, 5) AS INTEGER)) FROM tickets WHERE nomor_tiket LIKE 'TKT-%'"
        ).fetchone()
        next_seq = (row[0] + 1) if row[0] else 1001
        ticket_id = f"TKT-{next_seq}"
        conn.execute(
            "INSERT INTO tickets (nomor_tiket, kategori, deskripsi, nama_pelapor, kontak, "
            "alamat, status, estimasi) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, kategori, deskripsi, nama_pelapor, kontak, alamat, status, estimasi),
        )
        return ticket_id


def get_ticket(nomor_tiket: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE nomor_tiket = ?", (nomor_tiket,)).fetchone()
        return dict(row) if row else None
