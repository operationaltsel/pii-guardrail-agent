"""Synthetic NER dataset generator for Indonesian customer-support chat.

Usage:
    python generate_dataset.py --train 6000 --dev 800 --seed 42

Design goals (see ../ANNOTATION_GUIDELINE.md and docs/ner_model.md):
* Realistic variety: formal/informal register, lowercase chat, abbreviations, forms,
  multi-sentence messages, many Indonesian naming conventions and address formats.
* Hard negatives: common words that can be names (bunga, fajar, jaya), "jalan" that is not
  an address, cities without a street component, product names that look like names.
* Pipeline-aware: regex PII (NIK/email/phone) sometimes appears as ``[REDACT_*]``
  placeholders because the regex guardrail runs before NER in production.
* No leakage: train/dev use disjoint templates *and* disjoint lexicon pools; the gold test
  set's names/streets are removed from both (lexicon.py).
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

from annotation import Span, normalize_span, save_jsonl, to_inline
from lexicon import Pool, build_pools
from templates import (APPS, BRANDS, CLOSINGS, DEV_TEMPLATES, GREETINGS, HONORIFICS, INFORMAL,
                       MONTHS, PAYMENTS, PRODUCT_NAMES, PRODUCTS, TRAIN_TEMPLATES)

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated"
SLOT_RE = re.compile(r"\{([A-Z0-9]+)\}")

CATEGORY_WEIGHTS = {"person": 0.22, "address": 0.17, "both": 0.20, "form": 0.07, "regex": 0.10, "negative": 0.24}

BALI_BIRTH = ["Wayan", "Made", "Nyoman", "Ketut", "Putu", "Kadek", "Komang", "Gede", "Luh"]
CHINESE_SURNAME = ["Tan", "Lim", "Oei", "Liem", "Go", "Kwee", "Tjoa", "Ong", "The", "Khoo", "Tio", "Liauw"]
CHINESE_GIVEN = ["Siok", "Mei", "Hong", "Kiem", "Swie", "Hwa", "Lan", "Tjeng", "Bing", "Hok", "Giok",
                 "Ling", "Kian", "Sen", "Yong", "Tjie", "Hian", "Liong", "Bwee", "Djin"]
ARAB_FAMILY = ["Al-Attas", "Assegaf", "Al-Kaff", "Bahasuan", "Baswedan", "Al-Idrus", "Shahab", "Bafadal"]
ARAB_FIRST = ["Muhammad", "Ahmad", "Abdul", "Abdullah", "Umar", "Husein", "Hasan", "Fatimah", "Aisyah", "Salim"]


class Generator:
    def __init__(self, pool: Pool, rng: random.Random):
        self.p = pool
        self.r = rng

    # ------------------------------------------------------------------ names
    def name(self) -> str:
        r, p = self.r, self.p
        first, last = r.choice(p.first_names), r.choice(p.last_names)
        style = r.random()
        if style < 0.24:
            n = first
        elif style < 0.58:
            n = f"{first} {last}"
        elif style < 0.70:
            n = f"{first} {r.choice(p.first_names)} {last}"
        elif style < 0.78:
            n = f"{first} {r.choice(p.first_names)}"
        elif style < 0.83:  # Balinese
            n = f"{r.choice(['I', 'Ni', 'I Gusti', 'Ni Luh', 'Anak Agung', 'I Gusti Ayu'])} {r.choice(BALI_BIRTH)} {first}"
        elif style < 0.87:  # Chinese-Indonesian traditional
            n = f"{r.choice(CHINESE_SURNAME)} {r.choice(CHINESE_GIVEN)} {r.choice(CHINESE_GIVEN)}"
        elif style < 0.91:  # Arab-Indonesian
            n = f"{r.choice(ARAB_FIRST)} {first}" + (f" {r.choice(ARAB_FAMILY)}" if r.random() < 0.5 else "")
        elif style < 0.94:  # Bugis / Buton
            n = f"{r.choice(['Andi', 'La Ode', 'Wa Ode', 'Daeng'])} {first}"
        elif style < 0.97:  # Muslim Javanese/Sundanese common prefixes
            n = f"{r.choice(['Muhammad', 'M.', 'Moh.', 'Siti', 'Nur', 'Sri', 'Dewi', 'Putri'])} {first}"
        else:  # initials
            n = f"{first} {last[0]}." if r.random() < 0.5 else f"{first[0]}. {last}"
        return n

    # --------------------------------------------------------------- address
    def _num(self) -> str:
        n = str(self.r.choice([self.r.randint(1, 30), self.r.randint(1, 250)]))
        if self.r.random() < 0.12:
            n += self.r.choice("ABCD")
        return self.r.choice(["No. {}", "No.{}", "No {}", "no. {}", "no {}", "nomor {}", "{}", "No. {}"]).format(n)

    def _rtrw(self) -> str:
        rt, rw = self.r.randint(1, 15), self.r.randint(1, 12)
        fmt = self.r.choice(["RT {:02d}/RW {:02d}", "RT {:03d} RW {:03d}", "RT.{:02d}/RW.{:02d}", "RT {} RW {}",
                             "Rt {:02d} Rw {:02d}", "RT{:02d}/RW{:02d}", "RT {:02d} / RW {:02d}", "rt {}/rw {}"])
        return fmt.format(rt, rw)

    def _street(self) -> str:
        r = self.r
        prefix = r.choice(["Jl.", "Jl.", "Jl.", "Jl", "Jln.", "Jln", "Jalan", "Jalan", "JL.", "Gg.", "Gang", "Lr."])
        name = r.choice(self.p.streets)
        if r.random() < 0.08 and "Raya" not in name:
            name += " Raya"
        sep = "" if (prefix.endswith(".") and r.random() < 0.08) else " "
        s = f"{prefix}{sep}{name}"
        if r.random() < 0.12:
            s += f" {r.choice(['Km', 'KM', 'km'])} {r.randint(1, 40)}" + (f",{r.randint(1, 9)}" if r.random() < 0.3 else "")
        elif r.random() < 0.08:
            s += f" Kav. {r.randint(1, 80)}"
        if r.random() < 0.3 and prefix.startswith(("Jl", "Jalan", "JL")):
            s += f" Gg. {r.choice(self.p.streets)}"
        return s

    def _complex(self) -> str:
        r = self.r
        kind = r.choice(["Perumahan", "Perum", "Perum.", "Komplek", "Kompleks", "Komp.", "Cluster", "Griya",
                         "Villa", "Apartemen", "Apt.", "Rusun", "Ruko", "Gedung", "Wisma", "Menara"])
        name = r.choice(self.p.complexes)
        s = f"{kind} {name}"
        if kind in ("Apartemen", "Apt.", "Rusun"):
            s += f" Tower {r.choice('ABCDEFGH')} Lt. {r.randint(2, 40)} Unit {r.randint(1, 40)}{r.randint(1, 30):02d}"
        elif kind in ("Gedung", "Wisma", "Menara"):
            s += f" Lt. {r.randint(1, 30)}"
            if r.random() < 0.7:
                s += f", {self._street()} {self._num()}"
        else:
            s += f" Blok {r.choice('ABCDEFGHJK')}{r.randint(1, 12)}" + (f" {self._num()}" if r.random() < 0.8 else f"/{r.randint(1, 40)}")
        return s

    def _village(self) -> str:
        r = self.r
        head = r.choice([f"Dusun {r.choice(self.p.kelurahan)} {self._rtrw()}",
                         f"Kp. {r.choice(self.p.kelurahan)} {self._rtrw()}",
                         f"Kampung {r.choice(self.p.kelurahan)} {self._rtrw()}",
                         f"Br. {r.choice(self.p.kelurahan)}",
                         self._rtrw()])
        return f"{head}{r.choice([', ', ' '])}{self._kel()}"

    def _kel(self) -> str:
        return self.r.choice(["Kel. {}", "Kelurahan {}", "Desa {}", "Ds. {}", "Kel {}", "Kel. {}"]).format(self.r.choice(self.p.kelurahan))

    def _kec(self) -> str:
        return self.r.choice(["Kec. {}", "Kecamatan {}", "Kec {}"]).format(self.r.choice(self.p.kecamatan))

    def _city(self) -> str:
        c = self.r.choice(self.p.cities)
        return self.r.choice(["{}", "{}", "Kota {}", "Kab. {}", "Kabupaten {}"]).format(c)

    def address(self) -> str:
        r = self.r
        kind = r.random()
        if kind < 0.55:
            parts = [self._street() + " " + self._num() if r.random() < 0.85 else self._street()]
        elif kind < 0.78:
            parts = [self._complex()]
        elif kind < 0.90:
            parts = [self._village()]
        else:  # short informal
            s = f"{r.choice(['jl', 'jln', 'jl.', 'gg', 'jalan'])} {r.choice(self.p.streets).lower()} {r.randint(1, 99)}"
            parts = [s]
        if r.random() < 0.45 and kind < 0.78:
            parts.append(self._rtrw())
        if r.random() < 0.35 and kind < 0.78:
            parts.append(self._kel())
        if r.random() < 0.3:
            parts.append(self._kec())
        if r.random() < 0.72:
            parts.append(self._city())
        if r.random() < 0.22:
            parts.append(r.choice(self.p.provinces))
        if r.random() < 0.18:
            parts.append(str(r.randint(10110, 99999)))
        sep = r.choice([", ", ", ", ", ", " ", " - "])
        # rt/rw usually glued with a space to the street part
        text = parts[0]
        for part in parts[1:]:
            glue = " " if (part.upper().startswith("RT") and r.random() < 0.6) else sep
            text += glue + part
        return text

    # ------------------------------------------------------------- regex PII
    def nik(self) -> str:
        r = self.r
        prov = r.choice([11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 31, 32, 33, 34, 35, 36, 51, 52, 53, 61, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 81, 82, 91, 92])
        day = r.randint(1, 28) + (40 if r.random() < 0.5 else 0)
        digits = f"{prov:02d}{r.randint(1, 79):02d}{r.randint(1, 40):02d}{day:02d}{r.randint(1, 12):02d}{r.randint(50, 99) if r.random() < .7 else r.randint(0, 9):02d}{r.randint(1, 9999):04d}"
        if r.random() < 0.1:
            digits = " ".join(digits[i:i + 4] for i in range(0, 16, 4))
        return digits

    def phone(self) -> str:
        r = self.r
        body = f"8{r.choice([1, 1, 1, 2, 3, 5, 7, 8, 9])}{r.randint(1, 9)}{r.randint(10**6, 10**8 - 1)}"
        prefix = r.choice(["0", "0", "0", "+62", "62", "+62 "])
        num = prefix + body
        if r.random() < 0.3:
            num = f"{prefix}{body[:3]}-{body[3:7]}-{body[7:]}"
        elif r.random() < 0.15:
            num = f"{prefix}{body[:3]} {body[3:7]} {body[7:]}"
        return num

    def email(self, name: str | None = None) -> str:
        r = self.r
        base = (name or r.choice(self.p.first_names)).lower()
        base = re.sub(r"[^a-z ]", "", base).strip().replace(" ", r.choice([".", "_", ""]))
        base = base or "user"
        if r.random() < 0.5:
            base += str(r.randint(1, 999))
        domain = r.choice(["gmail.com", "gmail.com", "yahoo.com", "yahoo.co.id", "outlook.com", "hotmail.com",
                           "ymail.com", "nusatel.co.id", "kantor.go.id", "mail.ugm.ac.id", "icloud.com"])
        return f"{base}@{domain}"

    # ------------------------------------------------------------ context slots
    def context(self, slot: str) -> str:
        r = self.r
        return {
            "HON": lambda: r.choice(HONORIFICS),
            "CITY": lambda: r.choice(self.p.cities),
            "PROD": lambda: r.choice(PRODUCTS),
            "PRODNAME": lambda: r.choice(PRODUCT_NAMES),
            "BRAND": lambda: r.choice(BRANDS),
            "APP": lambda: r.choice(APPS),
            "PAY": lambda: r.choice(PAYMENTS),
            "TICKET": lambda: r.choice(["TKT-", "INC", "#", "IN", "SR-"]) + str(r.randint(10000, 9999999)),
            "CUSTNO": lambda: str(r.randint(10**9, 10**10 - 1)),
            "AMOUNT": lambda: r.choice(["Rp{}.000", "Rp {}.000", "{} ribu", "Rp{}rb"]).format(r.randint(50, 999)),
            "MONTH": lambda: r.choice(MONTHS),
            "YEAR": lambda: str(r.randint(2010, 2025)),
            "AGE": lambda: str(r.randint(18, 75)),
            "DATA": lambda: f"{r.choice([5, 10, 15, 20, 30, 50])}GB",
        }[slot]()


def _informalize(text: str, rng: random.Random, p: float) -> str:
    for formal, variants in INFORMAL.items():
        pattern = re.compile(rf"\b{re.escape(formal)}\b", re.IGNORECASE)
        text = pattern.sub(lambda m: rng.choice(variants) if rng.random() < p else m.group(), text)
    return text


def _typo(s: str, rng: random.Random) -> str:
    if len(s) < 5:
        return s
    i = rng.randint(1, len(s) - 3)
    if not (s[i].isalpha() and s[i + 1].isalpha()):
        return s
    return s[:i] + s[i + 1] + s[i] + s[i + 2:] if rng.random() < 0.6 else s[:i] + s[i + 1:]


def render(template: str, gen: Generator, rng: random.Random) -> tuple[str, list[Span]]:
    """Fill a template; returns text + spans. Style noise is applied per piece so that
    character offsets stay exact."""
    informal = rng.random() < 0.3
    lower = rng.random() < 0.35
    upper = (not lower) and rng.random() < 0.03
    ent_lower = rng.random() < 0.12
    placeholder_regex = rng.random() < 0.4  # regex PII already redacted upstream
    pieces: list[tuple[str, str | None]] = []
    person_name = None
    placeholder_idx = Counter()

    cursor = 0
    for m in SLOT_RE.finditer(template):
        pieces.append((template[cursor:m.start()], None))
        slot = m.group(1)
        if slot in ("PER", "PER2"):
            value = gen.name()
            person_name = person_name or value
            label = "PERSON"
            if rng.random() < 0.04:  # value already pseudonymised by the vault in an earlier turn
                placeholder_idx["NAMA"] += 1
                value, label = f"[REDACT_NAMA_{placeholder_idx['NAMA']}]", None
        elif slot in ("ADDR", "ADDR2"):
            value, label = gen.address(), "ADDRESS"
            if rng.random() < 0.04:
                placeholder_idx["ADDRESS"] += 1
                value, label = f"[REDACT_ADDRESS_{placeholder_idx['ADDRESS']}]", None
        elif slot in ("NIK", "EMAIL", "PHONE"):
            if placeholder_regex:
                value = f"[REDACT_{slot}]" if rng.random() < 0.6 else f"[REDACT_{slot}_{rng.randint(1, 3)}]"
            else:
                value = {"NIK": gen.nik, "PHONE": gen.phone}.get(slot, lambda: gen.email(person_name))()
            label = None
        else:
            value, label = gen.context(slot), None
        if label and ent_lower:
            value = value.lower()
        if label and rng.random() < 0.03:
            value = _typo(value, rng)
        pieces.append((value, label))
        cursor = m.end()
    pieces.append((template[cursor:], None))

    if rng.random() < 0.15:
        pieces.insert(0, (rng.choice(GREETINGS), None))
    if rng.random() < 0.15:
        pieces.append((rng.choice(CLOSINGS), None))

    text, spans = "", []
    for value, label in pieces:
        if value.startswith("[REDACT_"):  # placeholders are produced by code: never restyled
            text += value
            continue
        if label is None:
            if informal:
                value = _informalize(value, rng, 0.6)
            if rng.random() < 0.3:
                value = value.rstrip(".")
        if lower:
            value = value.lower()
        elif upper:
            value = value.upper()
        if label:
            spans.append(Span(len(text), len(text) + len(value), label))
        text += value
    # whitespace clean-up must keep offsets: only strip the ends (and shift spans)
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    spans = [normalize_span(text, Span(s.start - lead, s.end - lead, s.label)) for s in spans]
    return text, [s for s in spans if s.end > s.start]


def generate(templates: dict[str, list[str]], pool: Pool, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    gen = Generator(pool, rng)
    cats, weights = zip(*CATEGORY_WEIGHTS.items())
    rows, seen = [], set()
    while len(rows) < n:
        cat = rng.choices(cats, weights)[0]
        text, spans = render(rng.choice(templates[cat]), gen, rng)
        r = rng.random()
        # multi-sentence messages: 12% two sentences, 8% long rants of 3-7 sentences (entities
        # anywhere, incl. at the very end) so the model is robust on long real-world messages
        n_extra = 1 if r < 0.12 else rng.randint(2, 6) if r < 0.20 else 0
        for _ in range(n_extra):
            cat2 = rng.choices(cats, weights)[0] if rng.random() < 0.5 else "negative"
            text2, spans2 = render(rng.choice(templates[cat2]), gen, rng)
            offset = len(text) + 1
            text = f"{text} {text2}"
            spans += [Span(s.start + offset, s.end + offset, s.label) for s in spans2]
        if text in seen:
            continue
        seen.add(text)
        rows.append({"text": text, "entities": [s.as_list() for s in spans], "category": cat})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=6000)
    ap.add_argument("--dev", type=int, default=800)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    train_pool, dev_pool, stats = build_pools(exclude_gold=True)
    train = generate(TRAIN_TEMPLATES, train_pool, args.train, args.seed)
    dev = generate(DEV_TEMPLATES, dev_pool, args.dev, args.seed + 1)
    save_jsonl(train, OUT_DIR / "train.jsonl")
    save_jsonl(dev, OUT_DIR / "dev.jsonl")

    def summary(rows):
        ents = Counter(l for r in rows for *_, l in r["entities"])
        return {"sentences": len(rows), "entities": dict(ents),
                "no_entity_ratio": round(sum(not r["entities"] for r in rows) / len(rows), 3)}

    stats.update({"train": summary(train), "dev": summary(dev),
                  "n_templates": {"train": sum(map(len, TRAIN_TEMPLATES.values())),
                                  "dev": sum(map(len, DEV_TEMPLATES.values()))}})
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    print("\nExamples:")
    for row in train[:12]:
        from annotation import row_spans
        print(" ", to_inline(row["text"], row_spans(row)).replace("\n", "\\n"))


if __name__ == "__main__":
    main()
