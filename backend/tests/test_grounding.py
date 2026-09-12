"""The grounding agent rejects figures the engine never produced."""

from __future__ import annotations

import pytest

from backend.agents import grounding, judgement, llm
from backend.agents.goal import context_for, preset_intent
from backend.core.config import get_settings
from backend.models.goal import GoalType
from tests.test_allocation import decide

def balanced_context():
    return context_for("0x" + "1" * 40, "balanced", preset_intent(GoalType.BALANCED))


BRIEF = """\
Target stablecoin ratio: 80.0%
Drift from target: +79.6%
Engine confidence: 72%
[wallet] $40,700 across 22 positions, 100% of it volatile
"""


class TestCheck:
    def test_accepts_rounded_and_abbreviated_figures(self):
        report = grounding.check("A target of 80%, a drift of 79.6% and $40.7k held.", brief=BRIEF)
        assert report.grounded
        assert report.figures_checked == 3

    def test_ignores_sign(self):
        assert grounding.check("The book moves -79.6% toward target.", brief=BRIEF).grounded

    def test_rejects_invented_figures(self):
        report = grounding.check("Hold 43% in stablecoins, about $12,000.", brief=BRIEF)
        assert not report.grounded
        assert report.rejected == ["43%", "$12,000"]

    def test_text_without_figures_is_grounded(self):
        report = grounding.check("Volatility is high, so the engine leans defensive.", brief=BRIEF)
        assert report.grounded
        assert report.figures_checked == 0


@pytest.fixture
def model_available(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setattr(llm, "configured", lambda: True)
    yield
    get_settings.cache_clear()


def fake_structured(payload):
    async def structured(**kwargs):
        return payload

    return structured


@pytest.mark.asyncio
async def test_grounded_model_explanation_is_kept(monkeypatch, model_available):
    decision = decide()
    target = f"{decision.target_stablecoin_ratio:.0%}"
    monkeypatch.setattr(
        llm,
        "structured",
        fake_structured(
            {
                "summary": f"The engine targets {target} in stablecoins.",
                "reasoning": ["Volatility drives the result.", "Correlation supports it."],
                "caveats": ["The simulation is a risk model, not a forecast."],
            }
        ),
    )

    result = await judgement.explain(balanced_context(), decision, [])

    assert result.used_model is True
    assert result.grounding.grounded
    assert result.grounding.replaced_model_output is False


@pytest.mark.asyncio
async def test_ungrounded_model_explanation_is_replaced(monkeypatch, model_available):
    monkeypatch.setattr(
        llm,
        "structured",
        fake_structured(
            {
                "summary": "Hold 43.7% in stablecoins for a 12.3% return.",
                "reasoning": ["Trust the numbers.", "Really."],
                "caveats": ["None."],
            }
        ),
    )

    result = await judgement.explain(balanced_context(), decide(), [])

    assert result.used_model is False
    assert result.grounding.replaced_model_output is True
    assert result.grounding.rejected == ["43.7%", "12.3%"]
    assert result.grounding.grounded, "the replacement write-up must itself be grounded"


@pytest.mark.asyncio
async def test_fallback_is_grounded_without_a_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()

    result = await judgement.explain(balanced_context(), decide(), [])

    assert result.used_model is False
    assert result.grounding.grounded
