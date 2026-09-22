import asyncio

from cs_agent.guardrail.redactor import Redactor
from cs_agent.guardrail.vault import Vault


def run(coro):
    return asyncio.run(coro)


def test_vault_same_value_same_token():
    v = Vault()
    assert v.tokenize("PERSON", "Budi") == "[REDACT_NAMA_1]"
    assert v.tokenize("PERSON", "budi ") == "[REDACT_NAMA_1]"
    assert v.tokenize("PERSON", "Siti") == "[REDACT_NAMA_2]"
    assert v.tokenize("PHONE", "+62 812-3456-7890") == v.tokenize("PHONE", "081234567890")


def test_mask_mode_matches_brief_format():
    v = Vault(mode="mask")
    assert v.tokenize("PERSON", "Budi") == "[REDACT_NAMA]"
    assert v.tokenize("ADDRESS", "Jl.ABC") == "[REDACT_ADDRESS]"
    assert v.tokens == {}  # irreversible: nothing stored


def test_detokenize_roundtrip_and_serialisation():
    v = Vault()
    t = v.tokenize("EMAIL", "budi@gmail.com")
    v2 = Vault(v.to_dict())
    assert v2.detokenize(f"kirim ke {t}") == "kirim ke budi@gmail.com"
    assert v2.detokenize_obj({"kontak": t, "list": [t]}) == {"kontak": "budi@gmail.com", "list": ["budi@gmail.com"]}


def test_replace_known_respects_word_boundaries():
    v = Vault()
    v.tokenize("PERSON", "Budi")
    assert v.replace_known("Halo Budi, bukan Budiman") == "Halo [REDACT_NAMA_1], bukan Budiman"


def test_brief_example(fake_ner):
    # "Nama saya Budi, saya tinggal di Jl.ABC -> Nama saya [REDACT_NAMA], saya tinggal di [REDACT_ADDRESS]"
    r = Redactor(ner=fake_ner)
    res = run(r.redact("Nama saya Budi, saya tinggal di Jl.ABC", Vault(mode="mask")))
    assert res.text == "Nama saya [REDACT_NAMA], saya tinggal di [REDACT_ADDRESS]"


def test_pipeline_and_data_minimisation(fake_ner):
    r = Redactor(ner=fake_ner)
    v = Vault()
    text = "Saya Budi Santoso, NIK 3273011506900001, HP 0812-3456-7890, tinggal di Jl. Mawar No. 5, Bandung"
    res = run(r.redact(text, v))
    assert res.text == ("Saya [REDACT_NAMA_1], NIK [REDACT_NIK_1], HP [REDACT_PHONE_1], "
                        "tinggal di [REDACT_ADDRESS_1]")
    # NER service only ever saw the regex-redacted text
    assert fake_ner.received == ["Saya Budi Santoso, NIK [REDACT_NIK_1], HP [REDACT_PHONE_1], "
                                 "tinggal di Jl. Mawar No. 5, Bandung"]
    assert {f.label for f in res.findings} == {"PERSON", "NIK", "PHONE", "ADDRESS"}


def test_known_values_retokenised_without_ner(fake_ner):
    r = Redactor(ner=fake_ner)
    v = Vault()
    run(r.redact("Saya Budi Santoso", v))
    fake_ner.received.clear()
    # e.g. the agent's restored reply in history: vault handles it, no PII sent to NER
    assert r.redact_light("Baik Kak Budi Santoso, tiket dibuat", v) == "Baik Kak [REDACT_NAMA_1], tiket dibuat"
    assert fake_ner.received == []


def test_structured_tool_output_policy():
    r = Redactor()
    v = Vault()
    out = r.redact_structured({"nama_pelanggan": "Budi Santoso", "kontak": "budi@gmail.com", "paket": "VentraFiber 50",
                               "alamat_pemasangan": "Jl. Sudirman No. 10", "total_tagihan": 385000,
                               "catatan": "hubungi 081234567890"}, v)
    assert out == {"nama_pelanggan": "[REDACT_NAMA_1]", "kontak": "[REDACT_EMAIL_1]", "paket": "VentraFiber 50",
                   "alamat_pemasangan": "[REDACT_ADDRESS_1]", "total_tagihan": 385000,
                   "catatan": "hubungi [REDACT_PHONE_1]"}
