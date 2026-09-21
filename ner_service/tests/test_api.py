"""API contract tests for the NER service (runs against the real exported model)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL_DIR = Path(os.getenv("NER_MODEL_DIR", ROOT / "model"))
pytestmark = pytest.mark.skipif(not (MODEL_DIR / "model.onnx").exists(), reason="no exported model")


@pytest.fixture(scope="module")
def client():
    os.environ["NER_MODEL_DIR"] = str(MODEL_DIR)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 200


def test_brief_example(client):
    text = "Nama saya Budi Santoso dan tinggal di Jalan Sudirman Jakarta"
    r = client.post("/v1/ner", json={"text": text}).json()
    got = {(e["text"], e["label"]) for e in r["entities"]}
    assert got == {("Budi Santoso", "PERSON"), ("Jalan Sudirman Jakarta", "ADDRESS")}
    for e in r["entities"]:
        assert text[e["start"]:e["end"]] == e["text"]  # offsets are exact
    assert r["inference_ms"] > 0 and r["model_version"]


def test_negative_has_no_entities(client):
    r = client.post("/v1/ner", json={"text": "Saya mau jalan-jalan ke Bali, apakah roaming aktif?"}).json()
    assert r["entities"] == []


def test_placeholders_never_labelled(client):
    r = client.post("/v1/ner", json={"text": "Nama saya [REDACT_NAMA_1], HP [REDACT_PHONE]"}).json()
    assert r["entities"] == []


def test_long_text_is_not_truncated(client):
    filler = "Mohon dibantu karena internet sering putus terutama malam hari. " * 40
    text = filler + "Nama saya Budi Santoso."
    r = client.post("/v1/ner", json={"text": text}).json()
    assert any(e["text"] == "Budi Santoso" for e in r["entities"]), "entity at the end of a long text was missed"


def test_batch(client):
    r = client.post("/v1/ner/batch", json={"texts": ["Saya Andi", "Apa kabar?"]}).json()
    assert len(r["results"]) == 2 and r["results"][1] == []


def test_validation(client):
    assert client.post("/v1/ner", json={"text": "x" * 6000}).status_code == 422
    assert client.post("/v1/ner", json={"text": "hi", "threshold": 2}).status_code == 422


def test_metrics_and_model_card(client):
    assert "ner_inference_seconds" in client.get("/metrics").text
    card = client.get("/v1/model").json()
    assert card["labels"][0] == "O" and "threshold" in card
