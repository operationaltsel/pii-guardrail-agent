import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from cs_agent.guardrail.ner_client import NerClient, NerUnavailable  # noqa: E402
from cs_agent.guardrail.types import PiiSpan  # noqa: E402


class FakeNer(NerClient):
    """Deterministic stand-in for the NER service (unit tests must not need a model).
    Records every text it receives so tests can assert on data minimisation."""

    NAMES = ["Budi Santoso", "Siti Rahma", "Budi", "Andi Pratama"]
    ADDRESSES = ["Jl. Mawar No. 5, Bandung", "Jl.ABC", "Jl. Melati No. 9, Depok"]

    def __init__(self, down: bool = False):
        super().__init__("http://fake")
        self.down = down
        self.received: list[str] = []

    async def detect(self, text: str):
        if self.down:
            raise NerUnavailable("fake outage")
        self.received.append(text)
        spans, taken = [], []
        for label, values in (("ADDRESS", self.ADDRESSES), ("PERSON", self.NAMES)):
            for value in values:
                for m in re.finditer(re.escape(value), text):
                    if all(m.end() <= s or m.start() >= e for s, e in taken):
                        spans.append(PiiSpan(m.start(), m.end(), label, m.group(), "ner", 0.95))
                        taken.append((m.start(), m.end()))
        self.last_latency_ms = 1.0
        return spans


@pytest.fixture
def fake_ner():
    return FakeNer()
