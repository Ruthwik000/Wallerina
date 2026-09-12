"""The chat's suggested questions are answered from engine figures, no model."""

from __future__ import annotations

from types import SimpleNamespace as NS

import numpy as np
import pytest

from backend.core.config import get_settings
from backend.services import chat


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """No key: any model call would raise, proving presets never reach one."""
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def snapshot():
    portfolio = NS(
        total_value_usd=40_000.0,
        stablecoin_ratio=0.05,
        holdings=[
            NS(symbol="ETH", classification=NS(value="volatile"), value_usd=30_000.0),
            NS(symbol="MOG", classification="unknown", value_usd=900.0),
        ],
    )
    risk = NS(
        portfolio_annual_volatility=1.10,
        confidence=0.95,
        value_at_risk=0.0947,
        value_at_risk_usd=3_874.0,
        expected_shortfall=0.1318,
        max_drawdown=0.62,
        assets=[
            NS(symbol="USDC", risk_contribution=0.0, weight=0.05, annual_volatility=0.01, beta_to_portfolio=0.0),
            NS(symbol="ETH", risk_contribution=0.81, weight=0.75, annual_volatility=0.9, beta_to_portfolio=1.08),
        ],
    )
    simulation = NS(
        horizon_days=90, simulations=5_000, initial_value=40_000.0, p5=22_000.0,
        median_value=38_000.0, probability_of_loss=0.55, expected_drawdown=0.31,
    )
    estimate = NS(stable_mask=np.array([True, False]))
    return portfolio, risk, simulation, estimate


async def ask(message, monkeypatch=None):
    portfolio, risk, simulation, estimate = snapshot()
    return [
        event
        async for event in chat.stream_reply(
            message=message, history=[], portfolio=portfolio, risk=risk,
            simulation=simulation, estimate=estimate, excluded=[],
        )
    ]


@pytest.mark.asyncio
async def test_every_suggestion_is_answered_without_a_model(monkeypatch):
    async def fake_tool(estimate, tool_input):
        return {"p5_usd": 30_000.0, "probability_of_loss": 0.4, "expected_drawdown": 0.15}

    monkeypatch.setattr(chat, "_run_simulation_tool", fake_tool)

    for question in [
        "How risky is my portfolio right now?",
        "Which asset contributes the most risk, and why?",
        "What would happen if I moved half of it into stablecoins?",
        "What does my 5th percentile outcome actually mean?",
        "Why is one of my tokens classified as unknown?",
    ]:
        events = await ask(question)
        assert events[0]["type"] == "text", question
        assert events[0]["text"], question
        assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_matching_ignores_case_and_punctuation():
    events = await ask("  how RISKY is my portfolio right now  ")
    assert "110%" in events[0]["text"]
    assert "very high" in events[0]["text"]


@pytest.mark.asyncio
async def test_top_risk_names_the_largest_contributor():
    events = await ask("Which asset contributes the most risk, and why?")
    assert events[0]["text"].startswith("ETH contributes the most risk: 81%")


@pytest.mark.asyncio
async def test_half_stable_compares_against_current(monkeypatch):
    seen = []

    async def fake_tool(estimate, tool_input):
        seen.append(tool_input)
        return {"p5_usd": 30_000.0, "probability_of_loss": 0.4, "expected_drawdown": 0.15}

    monkeypatch.setattr(chat, "_run_simulation_tool", fake_tool)

    events = await ask("What would happen if I moved half of it into stablecoins?")

    assert seen == [{"stablecoin_ratio": 0.5, "horizon_days": 90}]
    assert "$22,000.00 to $30,000.00" in events[0]["text"]


@pytest.mark.asyncio
async def test_unknown_lists_unknown_tokens():
    events = await ask("Why is one of my tokens classified as unknown?")
    assert "MOG ($900.00)" in events[0]["text"]
    assert "ETH" not in events[0]["text"].split("unknown:")[1].split(".")[0]


@pytest.mark.asyncio
async def test_other_questions_still_need_the_model():
    with pytest.raises(chat.ChatUnavailableError):
        await ask("Should I worry about ETH gas fees?")
