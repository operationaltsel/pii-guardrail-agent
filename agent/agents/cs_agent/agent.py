"""Ventra customer-support agent (Google ADK + Gemini) with a PII guardrail.

Run locally:
    adk web agent/agents          # dev UI at http://localhost:8000
    adk run agent/agents/cs_agent # terminal chat
"""
from __future__ import annotations

import logging

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types as genai_types

from .config import get_settings
from .guardrail import PiiGuardrail
from .prompts import INSTRUCTION
from .tools import ALL_TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
guardrail = PiiGuardrail(settings)

root_agent = Agent(
    name="ventra_cs_agent",
    model=Gemini(
        model=settings.gemini_model,
        retry_options=genai_types.HttpRetryOptions(
            attempts=settings.gemini_retry_attempts,
            initial_delay=settings.gemini_retry_initial_delay_s,
            max_delay=settings.gemini_retry_max_delay_s,
        ),
    ),
    description="Customer support Ventra dengan guardrail PII (regex + NER).",
    instruction=INSTRUCTION,
    tools=ALL_TOOLS,
    before_model_callback=guardrail.before_model,   # the guardrail required by the brief
    after_model_callback=guardrail.after_model,
    before_tool_callback=guardrail.before_tool,
    after_tool_callback=guardrail.after_tool,
)
