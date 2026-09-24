import re

import pytest

from cs_agent.guardrail.regex_detector import RegexDetector, nik_is_valid

det = RegexDetector()


def labels(text):
    return [(s.label, s.text) for s in det.detect(text)]


# ------------------------------------------------------------------ NIK
@pytest.mark.parametrize("text,nik", [
    ("NIK saya 3273011506900001 ya", "3273011506900001"),
    ("nik: 3273 0115 0690 0001", "3273 0115 0690 0001"),
    ("KTP 3578014107900002.", "3578014107900002"),
])
def test_nik_inside_sentence(text, nik):
    assert ("NIK", nik) in labels(text)


def test_brief_baseline_regex_misses_nik_inside_sentence():
    # the brief's ^[0-9]{16}$ only matches when the whole message is the NIK
    assert re.search(r"^[0-9]{16}$", "NIK saya 3273011506900001") is None
    assert labels("NIK saya 3273011506900001") == [("NIK", "3273011506900001")]


def test_nik_structure_validation():
    assert nik_is_valid("3273011506900001")      # male, 15-06-90
    assert nik_is_valid("3374116512880001")      # female: day 65 -> 25
    assert not nik_is_valid("0073011506900001")  # province 00
    assert not nik_is_valid("3273011513900001")  # month 13
    assert not nik_is_valid("3273013102900001")  # 31 February
    # invalid structure is still redacted (fail-safe), only with a lower score
    [span] = det.detect("nomor 9999999999999999")
    assert span.label == "NIK" and span.score < 1.0


def test_nik_not_part_of_longer_number():
    assert labels("rekening 12345678901234567890") == []


# ---------------------------------------------------------------- email
@pytest.mark.parametrize("email", ["budi.s@gmail.com", "dian_p+cs@yahoo.co.id", "finance@pt-maju.co.id"])
def test_email(email):
    assert ("EMAIL", email) in labels(f"email saya {email}, tolong kirim invoice")


def test_email_obfuscated():
    assert labels("email andi.wijaya at gmail dot com ya") == [("EMAIL", "andi.wijaya at gmail dot com")]


def test_brief_email_regex_unescaped_dot_bug():
    brief = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+.[a-zA-Z]{2,}"
    assert re.fullmatch(brief, "budi@gmailxcom")          # '.' matches any char in the brief
    assert labels("budi@gmailxcom") == []


# ---------------------------------------------------------------- phone
@pytest.mark.parametrize("phone", ["081234567890", "0812-3456-7890", "+62 812-3456-7890", "6281399887766",
                                   "0821 1234 5678", "0812.9988.7766", "+6285712345678", "(0542) 123456",
                                   "021-5551234", "0274 512345"])
def test_phone_formats(phone):
    assert ("PHONE", phone) in labels(f"hubungi {phone} ya")


def test_brief_phone_regex_is_invalid():
    with pytest.raises(re.error):
        re.compile(r"(+62|62|0)8[1-9][0-9]{6,9}")


@pytest.mark.parametrize("text", ["tanggal 02-10-2024", "jam 08.30", "Rp 150.000", "nomor pelanggan 1122334455",
                                  "tiket TKT-1001", "paket 50 Mbps", "kode pos 40162", "INC1234567"])
def test_no_false_positive(text):
    assert labels(text) == []


def test_multiple_and_priority():
    text = "Saya Dian, NIK 3171234501900001, HP +62 812-3456-7890, email dian@yahoo.co.id"
    assert [l for l, _ in labels(text)] == ["NIK", "PHONE", "EMAIL"]
