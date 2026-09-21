"""Regex-based PII detection for structured identifiers: NIK (KTP), email, phone number.

Regex is the right tool here: these identifiers have a fixed *shape*, so a pattern gives
~100% recall at microsecond cost with zero ML. Names and addresses have no fixed shape —
that is what the NER service is for.

Differences vs. the baseline regexes in the assignment brief (and why):

| PII   | Brief                                   | Here                                                    |
|-------|-----------------------------------------|---------------------------------------------------------|
| NIK   | ``^[0-9]{16}$``                         | ``^``/``$`` only match a message that is *only* a NIK;  |
|       |                                         | we search inside text, allow ``3273 0115 0690 0001``    |
|       |                                         | grouping, and validate the NIK structure (see below).   |
| Email | ``...@[a-zA-Z0-9.-]+.[a-zA-Z]{2,}``     | the unescaped ``.`` matches any char; escaped here, plus|
|       |                                         | obfuscated ``nama at gmail dot com``.                   |
| Phone | ``(+62|62|0)8[1-9][0-9]{6,9}``          | unescaped ``+`` is a regex error; escaped here, allows  |
|       |                                         | separators ``0812-3456-7890`` / ``+62 812 ...`` and     |
|       |                                         | landlines ``(022) 2501234``.                            |

NIK structure (Permendagri): PP KK CC DDMMYY SSSS — province, regency, district, birth date
(day + 40 for women), sequence. A 16-digit number failing validation is *still* redacted
(fail-safe: it may be a card/account number) but reported with a lower score.
"""
from __future__ import annotations

import re

from .types import PiiSpan

VALID_PROVINCES = {11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 31, 32, 33, 34, 35, 36, 51, 52, 53,
                   61, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 81, 82, 91, 92, 93, 94, 95, 96}

NIK_RE = re.compile(r"(?<![\d])\d(?:[ .\-]?\d){15}(?![\d])")
EMAIL_RE = re.compile(r"(?<![\w.%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b")
EMAIL_OBFUSCATED_RE = re.compile(
    r"(?<![\w.])[A-Za-z0-9._%+\-]+\s*(?:\[at\]|\(at\)|\s+at\s+)\s*[A-Za-z0-9\-]+"
    r"(?:\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\.)\s*[A-Za-z0-9\-]+)*\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*[A-Za-z]{2,}\b",
    re.IGNORECASE)
MOBILE_RE = re.compile(r"(?<![\w+])(?:\+62|62|0)[ .\-]?\(?8\d{1,2}\)?(?:[ .\-]?\d){6,10}(?!\d)")
LANDLINE_RE = re.compile(r"(?<![\w+])(?:\(0\d{2,3}\)|(?:\+62|62|0)[ \-]?[2-9]\d{1,2})[ .\-]?\d{3,4}[ .\-]?\d{3,5}(?!\d)")

PRIORITY = {"NIK": 3, "EMAIL": 2, "PHONE": 1}


def nik_is_valid(digits: str) -> bool:
    if len(digits) != 16 or not digits.isdigit():
        return False
    prov, kab, kec = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    day, month = int(digits[6:8]), int(digits[8:10])
    seq = int(digits[12:16])
    day = day - 40 if day > 40 else day
    return prov in VALID_PROVINCES and kab > 0 and kec > 0 and 1 <= day <= 31 and 1 <= month <= 12 and seq > 0


def _phone_digits_ok(raw: str) -> bool:
    d = re.sub(r"\D", "", raw)
    if d.startswith("62"):
        d = "0" + d[2:]
    return 9 <= len(d) <= 13


class RegexDetector:
    def detect(self, text: str) -> list[PiiSpan]:
        found: list[PiiSpan] = []
        for m in NIK_RE.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            found.append(PiiSpan(m.start(), m.end(), "NIK", m.group(), "regex", 1.0 if nik_is_valid(digits) else 0.7))
        for rx in (EMAIL_RE, EMAIL_OBFUSCATED_RE):
            for m in rx.finditer(text):
                found.append(PiiSpan(m.start(), m.end(), "EMAIL", m.group(), "regex"))
        for rx in (MOBILE_RE, LANDLINE_RE):
            for m in rx.finditer(text):
                if _phone_digits_ok(m.group()):
                    found.append(PiiSpan(m.start(), m.end(), "PHONE", m.group(), "regex"))
        return resolve_overlaps(found)


def resolve_overlaps(spans: list[PiiSpan]) -> list[PiiSpan]:
    """Keep a non-overlapping set: longer span wins, then higher label priority."""
    ordered = sorted(spans, key=lambda s: (-(s.end - s.start), -PRIORITY.get(s.label, 0), s.start))
    kept: list[PiiSpan] = []
    for s in ordered:
        if all(s.end <= k.start or s.start >= k.end for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)
