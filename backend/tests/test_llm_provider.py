"""Tests for model provider selection.

The contract: Bedrock authenticates through the AWS credential chain and needs
no key of its own, the Anthropic path needs one, and with neither configured
the agents fall back to deterministic output rather than failing.
"""

from __future__ import annotations

import pytest

from backend.agents import llm
from backend.core.config import get_settings


@pytest.fixture(autouse=True)
def clean_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def configure(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


class TestBedrockDefault:
    def test_bedrock_is_the_default_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        get_settings.cache_clear()
        assert llm.provider() == llm.BEDROCK

    def test_bedrock_needs_no_api_key(self, monkeypatch):
        """The point of Bedrock here: IAM replaces the key entirely."""
        configure(
            monkeypatch,
            LLM_PROVIDER="bedrock",
            AWS_ENABLED="true",
            ANTHROPIC_API_KEY="",
        )
        assert llm.configured() is True

    def test_bedrock_requires_aws_enabled(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="bedrock", AWS_ENABLED="false")
        assert llm.configured() is False

        with pytest.raises(llm.ModelUnavailable, match="AWS_ENABLED"):
            llm.client()

    def test_model_id_is_namespaced_for_bedrock(self, monkeypatch):
        """Bedrock ids carry a vendor prefix; the first-party API does not."""
        configure(
            monkeypatch,
            LLM_PROVIDER="bedrock",
            AWS_ENABLED="true",
            CHAT_MODEL="claude-opus-5",
        )
        assert llm.model_id() == "anthropic.claude-opus-5"

    def test_prefix_is_not_applied_twice(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="bedrock",
            AWS_ENABLED="true",
            CHAT_MODEL="anthropic.claude-opus-5",
        )
        assert llm.model_id() == "anthropic.claude-opus-5"

    def test_client_is_the_bedrock_client(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="bedrock",
            AWS_ENABLED="true",
            AWS_REGION="us-east-1",
        )
        assert type(llm.client()).__name__ == "AsyncAnthropicBedrockMantle"

    def test_bedrock_region_overrides_aws_region(self, monkeypatch):
        """Model availability is region-specific, so it must be separable."""
        configure(
            monkeypatch,
            LLM_PROVIDER="bedrock",
            AWS_ENABLED="true",
            AWS_REGION="ap-south-1",
            BEDROCK_REGION="us-east-1",
        )
        assert llm.describe()["region"] == "us-east-1"


class TestAnthropicPath:
    def test_requires_a_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
        assert llm.configured() is False

        with pytest.raises(llm.ModelUnavailable, match="ANTHROPIC_API_KEY"):
            llm.client()

    def test_client_is_the_first_party_client(self, monkeypatch):
        configure(
            monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-test"
        )
        assert type(llm.client()).__name__ == "AsyncAnthropic"

    def test_model_id_is_unprefixed(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="anthropic",
            ANTHROPIC_API_KEY="sk-test",
            CHAT_MODEL="claude-opus-5",
        )
        assert llm.model_id() == "claude-opus-5"


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_preset_goal_needs_no_provider(self, monkeypatch):
        """A preset must never reach a model, configured or not."""
        from backend.agents.goal import interpret

        configure(monkeypatch, LLM_PROVIDER="bedrock", AWS_ENABLED="false")

        intent = await interpret("Preserve capital")
        assert intent.source == "preset"
        assert intent.goal_type == "capital_preservation"

    @pytest.mark.asyncio
    async def test_free_text_falls_back_without_a_provider(self, monkeypatch):
        from backend.agents.goal import interpret

        configure(monkeypatch, LLM_PROVIDER="bedrock", AWS_ENABLED="false")

        intent = await interpret("I want to buy a house in six months")
        assert intent.goal_type == "balanced"
        assert intent.interpretation is not None

    @pytest.mark.asyncio
    async def test_judgement_falls_back_to_deterministic_prose(self, monkeypatch):
        from backend.agents import judgement
        from backend.agents.goal import preset_intent
        from backend.models.goal import GoalType
        from tests.test_allocation import decide

        configure(monkeypatch, LLM_PROVIDER="bedrock", AWS_ENABLED="false")

        result = await judgement.explain(
            preset_intent(GoalType.BALANCED), decide(), []
        )

        assert result.used_model is False
        assert result.summary
        assert result.reasoning
