"""End-to-end through the real ADK runner, with a recording fake LLM instead of Gemini.

Proves the core invariant of the system: across a multi-turn conversation with a tool call,
**no raw PII appears in any request sent to the LLM**, while the tool still receives the
real values and the user still sees their own data in the reply.
"""
import asyncio
import json
from typing import AsyncGenerator

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from conftest import FakeNer
from cs_agent import tools
from cs_agent.config import Settings
from cs_agent.guardrail import PiiGuardrail
from cs_agent.guardrail.callbacks import FAIL_CLOSED_MESSAGE

REQUESTS: list[str] = []  # module-level: BaseLlm is a pydantic model
RAW_PII = ["Budi Santoso", "3273011506900001", "0812-3456-7890", "Jl. Mawar No. 5, Bandung", "budi@gmail.com"]


class RecordingLlm(BaseLlm):
    """Turn 1: calls buat_tiket_pengaduan with placeholders. Turn 2: confirms in text."""

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        REQUESTS.append(llm_request.model_dump_json(exclude={"tools_dict", "config"}))
        last = llm_request.contents[-1].parts[-1]
        if last.function_response is not None:
            tid = last.function_response.response.get("nomor_tiket")
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                text=f"Baik Kak [REDACT_NAMA_1], tiket {tid} sudah dibuat. Teknisi akan menghubungi [REDACT_PHONE_1].")]))
            return
        if "tiket" in (last.text or "").lower():
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                name="buat_tiket_pengaduan",
                args={"kategori": "internet", "deskripsi": "Internet mati", "nama_pelapor": "[REDACT_NAMA_1]",
                      "kontak": "[REDACT_PHONE_1]", "alamat": "[REDACT_ADDRESS_1]"}))]))
            return
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Siap, ada yang bisa dibantu?")]))


def build(ner, **settings):
    llm = RecordingLlm(model="recording-fake")
    REQUESTS.clear()
    g = PiiGuardrail(Settings(**settings), ner_client=ner)
    agent = Agent(name="cs_test", model=llm, instruction="test", tools=tools.ALL_TOOLS,
                  before_model_callback=g.before_model, after_model_callback=g.after_model,
                  before_tool_callback=g.before_tool, after_tool_callback=g.after_tool)
    return InMemoryRunner(agent=agent, app_name="t")


async def chat(runner, messages):
    session = await runner.session_service.create_session(app_name="t", user_id="u")
    replies = []
    for msg in messages:
        texts = []
        async for ev in runner.run_async(user_id="u", session_id=session.id,
                                         new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
            if ev.content and ev.content.parts:
                texts += [p.text for p in ev.content.parts if p.text]
        replies.append(" ".join(texts))
    return replies


def test_no_raw_pii_reaches_llm_and_tool_gets_real_values():
    tools.TOOL_AUDIT.clear()
    runner = build(FakeNer())
    replies = asyncio.run(chat(runner, [
        "Halo, saya Budi Santoso, NIK 3273011506900001, HP 0812-3456-7890, email budi@gmail.com. "
        "Internet di Jl. Mawar No. 5, Bandung mati.",
        "Tolong buatkan tiket ya",
    ]))
    sent = "\n".join(REQUESTS)
    for value in RAW_PII:
        assert value not in sent, f"raw PII leaked to LLM: {value}"
    assert "[REDACT_NAMA_1]" in sent and "[REDACT_NIK_1]" in sent and "[REDACT_ADDRESS_1]" in sent

    # the tool ran with real values (server-side), not placeholders
    assert tools.TOOL_AUDIT[-1] == {"tool": "buat_tiket_pengaduan", "nama_pelapor": "Budi Santoso",
                                    "kontak": "0812-3456-7890", "alamat": "Jl. Mawar No. 5, Bandung"}
    # the user sees their own data restored in the final reply
    assert "Baik Kak Budi Santoso" in replies[-1] and "0812-3456-7890" in replies[-1]


def test_restored_history_is_retokenised_next_turn():
    runner = build(FakeNer())
    asyncio.run(chat(runner, ["Saya Budi Santoso, HP 0812-3456-7890", "Tolong buatkan tiket", "terima kasih"]))
    last_request = json.loads(REQUESTS[-1])
    history = json.dumps(last_request["contents"])
    assert "Budi Santoso" not in history and "0812-3456-7890" not in history
    assert "Baik Kak [REDACT_NAMA_1]" in history  # the agent's own earlier reply, tokenised again


def test_fail_closed_when_ner_down():
    runner = build(FakeNer(down=True), fail_mode="closed")
    [reply] = asyncio.run(chat(runner, ["Nama saya Budi Santoso"]))
    assert reply == FAIL_CLOSED_MESSAGE
    assert REQUESTS == []  # the LLM was never called


def test_fail_open_degrades_to_regex_only():
    runner = build(FakeNer(down=True), fail_mode="open")
    asyncio.run(chat(runner, ["NIK 3273011506900001, nama Budi"]))
    sent = "\n".join(REQUESTS)
    assert "3273011506900001" not in sent  # regex still protects structured PII
    assert "[REDACT_NIK_1]" in sent


def test_mask_mode_uses_brief_format():
    runner = build(FakeNer(), redaction_mode="mask")
    asyncio.run(chat(runner, ["Nama saya Budi, saya tinggal di Jl.ABC"]))
    assert "Nama saya [REDACT_NAMA], saya tinggal di [REDACT_ADDRESS]" in REQUESTS[-1]


def test_sent_to_ai_report_shows_tokenized_message_only():
    runner = build(FakeNer())

    async def run():
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        reports = []
        async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=types.Content(
                role="user", parts=[types.Part(text="Saya Budi Santoso, NIK 3273011506900001")])):
            report = (ev.actions.state_delta or {}).get("pii_report")
            if report:
                reports.append(report)
        return reports

    reports = asyncio.run(run())
    assert reports and reports[0]["sent_to_ai"] == "Saya [REDACT_NAMA_1], NIK [REDACT_NIK_1]"
    for value in RAW_PII:
        assert value not in json.dumps(reports)
