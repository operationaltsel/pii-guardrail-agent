"""Load lexicons, remove overlap with the gold test set, and split train/dev pools.

Leakage control
---------------
* Every distinctive token that appears inside a gold PERSON/ADDRESS span is removed from
  the name / street / complex / kelurahan / kecamatan pools. The gold test set therefore
  measures generalisation to *unseen* names and streets (a conservative estimate).
* Common Indonesian name particles (Muhammad, Siti, Ni, Made, ...) and generic address
  words (Raya, Barat, Indah, ...) are exempt — excluding them would be unrealistic.
* City / province names are a closed set (~514 regencies) and are allowed to overlap.
* Remaining entries are split deterministically into train (85%) and dev (15%) pools so
  the dev set also contains unseen lexical items.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from annotation import load_gold

LEX_DIR = Path(__file__).resolve().parent.parent / "data" / "lexicon"
GOLD_PATH = Path(__file__).resolve().parent.parent / "data" / "gold" / "test_gold.txt"

NAME_PARTICLES = {
    "i", "ni", "made", "wayan", "nyoman", "ketut", "putu", "kadek", "komang", "gede", "luh",
    "gusti", "ayu", "ngurah", "wa", "la", "ode", "al", "da", "de", "br", "boru", "bin", "binti",
    "muhammad", "muh", "moh", "mohammad", "siti", "nur", "sri", "abdul", "andi", "dewi", "putri", "putra",
}
ADDRESS_GENERIC = {
    "jl", "jln", "jalan", "gg", "gang", "lr", "no", "rt", "rw", "kel", "kelurahan", "kec",
    "kecamatan", "desa", "dusun", "kab", "kabupaten", "kota", "blok", "lt", "unit", "tower",
    "raya", "barat", "timur", "utara", "selatan", "tengah", "baru", "lama", "indah", "permai",
    "jaya", "asri", "city", "residence", "perum", "perumahan", "komplek", "apartemen", "gedung",
    "graha", "km", "kav", "kavling", "cluster", "ruko", "br", "kp", "h", "dr", "jend", "jenderal",
    "letjen", "ir", "sektor", "mas", "garden", "park", "taman", "villa", "griya", "pondok", "bukit",
}


def _read_lines(name: str) -> list[str]:
    lines = (LEX_DIR / name).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", s.lower()) if len(t) > 1}


def _is_dev(item: str, dev_ratio: float = 0.15) -> bool:
    h = int(hashlib.md5(item.encode("utf-8")).hexdigest(), 16)
    return (h % 1000) / 1000 < dev_ratio


@dataclass
class Pool:
    first_names: list[str] = field(default_factory=list)
    last_names: list[str] = field(default_factory=list)
    streets: list[str] = field(default_factory=list)
    complexes: list[str] = field(default_factory=list)
    kelurahan: list[str] = field(default_factory=list)
    kecamatan: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)


def gold_tokens() -> tuple[set[str], set[str]]:
    person, address = set(), set()
    for row in load_gold(GOLD_PATH):
        for s, e, label in row["entities"]:
            toks = _tokens(row["text"][s:e])
            if label == "PERSON":
                person |= toks
            elif label == "ADDRESS":
                address |= toks
    return person, address


def build_pools(exclude_gold: bool = True) -> tuple[Pool, Pool, dict]:
    regions: dict[str, list[str]] = {}
    for line in _read_lines("regions.txt"):
        kind, name = line.split("|", 1)
        regions.setdefault(kind, []).append(name)
    city_tokens = set().union(*(_tokens(c) for c in regions["city"] + regions["province"]))

    raw = {
        "first_names": _read_lines("first_names.txt"),
        "last_names": _read_lines("last_names.txt"),
        "streets": _read_lines("streets.txt"),
        "complexes": _read_lines("complexes.txt"),
        "kelurahan": regions["kelurahan"],
        "kecamatan": regions["kecamatan"],
    }
    stats = {"removed": {}}
    if exclude_gold:
        g_person, g_address = gold_tokens()
        g_person -= NAME_PARTICLES
        g_address -= ADDRESS_GENERIC | city_tokens
        banned = {"first_names": g_person, "last_names": g_person}
        for k in ("streets", "complexes", "kelurahan", "kecamatan"):
            # gold names must not leak via street names either (e.g. "Jl. Agus Salim")
            banned[k] = g_address | g_person
        for k, items in raw.items():
            kept = [x for x in dict.fromkeys(items) if not (_tokens(x) & banned[k])]
            stats["removed"][k] = len(set(items)) - len(kept)
            raw[k] = kept

    train, dev = Pool(), Pool()
    for k, items in raw.items():
        for x in items:
            getattr(dev if _is_dev(x) else train, k).append(x)
    # closed-set geography is shared by both pools
    for p in (train, dev):
        p.cities = list(regions["city"])
        p.provinces = list(regions["province"]) + list(regions["province_abbr"])
    stats["train_sizes"] = {k: len(v) for k, v in vars(train).items()}
    stats["dev_sizes"] = {k: len(v) for k, v in vars(dev).items()}
    return train, dev, stats
