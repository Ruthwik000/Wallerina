"""Tests for the NVIDIA NIM model layer.

The contract: every model call goes to NIM's OpenAI-compatible API with
NVIDIA_API_KEY, failures surface as actionable messages, and without a key the
agents fall back to deterministic output rather than failing. No test touches
the network; the client is faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import httpx
import openai
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


def status_error(cls, status: int, message: str = "boom"):
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=request), body=None)


def completion(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


def tool_call(name, arguments, id="call_1"):
    return NS(id=id, type="function", function=NS(name=name, arguments=arguments))


def chunk(content=None, tool_calls=None, finish_reason=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish_reason)])


def delta_call(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


class FakeClient:
    """Stands in for openai.AsyncOpenAI. Each create() pops the next response."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat = NS(completions=NS(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if kwargs.get("stream"):
            async def stream():
                for item in response:
                    yield item
            return stream()
        return response


def use_client(monkeypatch, fake: FakeClient):
    configure(monkeypatch, NVIDIA_API_KEY="nvapi-test")
    monkeypatch.setattr(llm, "client", lambda: fake)


class TestConfiguration:
    def test_requires_a_key(self, monkeypatch):
        configure(monkeypatch, NVIDIA_API_KEY="")
        assert llm.configured() is False

        with pytest.raises(llm.ModelUnavailable, match="NVIDIA_API_KEY"):
            llm.client()

    def test_client_points_at_nim(self, monkeypatch):
        configure(monkeypatch, NVIDIA_API_KEY="nvapi-test")
        client = llm.client()
        assert str(client.base_url).startswith("https://integrate.api.nvidia.com/v1")

    def test_model_is_configurable(self, monkeypatch):
        configure(monkeypatch, CHAT_MODEL="deepseek-ai/deepseek-v4-flash-0731")
        assert llm.describe() == {
            "provider": "nvidia-nim",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "configured": llm.configured(),
        }


class TestErrors:
    def test_bad_key_is_explained(self):
        error = llm.translate(status_error(openai.AuthenticationError, 401))
        assert isinstance(error, llm.ModelError)
        assert "NVIDIA_API_KEY" in str(error)

    def test_unknown_model_is_explained(self):
        assert "CHAT_MODEL" in str(llm.translate(status_error(openai.NotFoundError, 404)))

    def test_rate_limit_is_explained(self):
        assert "rate limit" in str(llm.translate(status_error(openai.RateLimitError, 429)))


class TestStructured:
    @pytest.mark.asyncio
    async def test_forces_the_function_and_returns_its_arguments(self, monkeypatch):
        fake = FakeClient([completion(tool_calls=[tool_call("record", '{"a": 1}')])])
        use_client(monkeypatch, fake)

        payload = await llm.structured(system="s", prompt="p", name="record", description="d", schema={})

        assert payload == {"a": 1}
        assert fake.calls[0]["tool_choice"] == {"type": "function", "function": {"name": "record"}}

    @pytest.mark.asyncio
    async def test_retries_with_auto_when_forced_choice_is_rejected(self, monkeypatch):
        fake = FakeClient(
            [
                status_error(openai.BadRequestError, 400, "tool_choice not supported"),
                completion(tool_calls=[tool_call("record", '{"a": 2}')]),
            ]
        )
        use_client(monkeypatch, fake)

        payload = await llm.structured(system="s", prompt="p", name="record", description="d", schema={})

        assert payload == {"a": 2}
        assert fake.calls[1]["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_accepts_json_in_text(self, monkeypatch):
        use_client(monkeypatch, FakeClient([completion(content='```json\n{"a": 3}\n```')]))

        payload = await llm.structured(system="s", prompt="p", name="record", description="d", schema={})

        assert payload == {"a": 3}

    @pytest.mark.asyncio
    async def test_no_output_is_an_error(self, monkeypatch):
        use_client(monkeypatch, FakeClient([completion(content="no idea")]))

        with pytest.raises(llm.ModelError):
            await llm.structured(system="s", prompt="p", name="record", description="d", schema={})

    @pytest.mark.asyncio
    async def test_goal_extraction_uses_the_model(self, monkeypatch):
        from backend.agents.goal import interpret

        arguments = json.dumps(
            {
                "goal_type": "capital_preservation",
                "risk_tolerance": "low",
                "maximum_drawdown": 0.1,
                "time_horizon_days": 180,
                "interpretation": "You want safety.",
            }
        )
        use_client(monkeypatch, FakeClient([completion(tool_calls=[tool_call("record_goal", arguments)])]))

        intent = await interpret("I want to buy a house in six months")

        assert intent.source == "llm"
        assert intent.goal_type == "capital_preservation"
        assert intent.time_horizon_days == 180


class TestChatStream:
    @pytest.mark.asyncio
    async def test_tool_call_round_trip(self, monkeypatch):
        """The model asks for a simulation, gets the result, then answers."""
        from backend.services import chat

        first_turn = [
            chunk(tool_calls=[delta_call(0, id="call_9", name="run_simulation", arguments='{"stablecoin_')]),
            chunk(tool_calls=[delta_call(0, arguments='ratio": 0.5}')]),
            chunk(finish_reason="tool_calls"),
        ]
        second_turn = [chunk(content="Risk "), chunk(content="falls."), chunk(finish_reason="stop")]
        fake = FakeClient([first_turn, second_turn])
        use_client(monkeypatch, fake)

        seen_inputs = []

        async def fake_tool(estimate, tool_input):
            seen_inputs.append(tool_input)
            return {"probability_of_loss": 0.3}

        monkeypatch.setattr(chat, "build_context", lambda *args: "context")
        monkeypatch.setattr(chat, "_run_simulation_tool", fake_tool)

        events = [
            event
            async for event in chat.stream_reply(
                message="What if half were stablecoins?",
                history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
                portfolio=None, risk=None, simulation=None, estimate=None, excluded=[],
            )
        ]

        assert seen_inputs == [{"stablecoin_ratio": 0.5}]
        assert "".join(e["text"] for e in events if e["type"] == "text") == "Risk falls."
        assert {"type": "tool", "name": "run_simulation"} in events
        assert events[-1] == {"type": "done"}

        follow_up = fake.calls[1]["messages"]
        assert follow_up[-2]["tool_calls"][0]["id"] == "call_9"
        assert follow_up[-1] == {
            "role": "tool",
            "tool_call_id": "call_9",
            "content": json.dumps({"probability_of_loss": 0.3}),
        }

    @pytest.mark.asyncio
    async def test_failure_becomes_an_error_event(self, monkeypatch):
        from backend.services import chat

        use_client(monkeypatch, FakeClient([status_error(openai.AuthenticationError, 401)]))
        monkeypatch.setattr(chat, "build_context", lambda *args: "context")

        events = [
            event
            async for event in chat.stream_reply(
                message="hi", history=[], portfolio=None, risk=None,
                simulation=None, estimate=None, excluded=[],
            )
        ]

        assert events[0]["type"] == "error"
        assert "NVIDIA_API_KEY" in events[0]["message"]
        assert events[-1] == {"type": "done"}

    def test_history_is_normalised(self):
        from backend.services.chat import to_messages

        messages = to_messages(
            [
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "c"},
                {"role": "user", "content": "dangling"},
            ]
        )

        assert messages == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"}]


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_preset_goal_needs_no_model(self, monkeypatch):
        """A preset must never reach a model, configured or not."""
        from backend.agents.goal import interpret

        configure(monkeypatch, NVIDIA_API_KEY="")

        intent = await interpret("Preserve capital")
        assert intent.source == "preset"
        assert intent.goal_type == "capital_preservation"

    @pytest.mark.asyncio
    async def test_free_text_falls_back_without_a_key(self, monkeypatch):
        from backend.agents.goal import interpret

        configure(monkeypatch, NVIDIA_API_KEY="")

        intent = await interpret("I want to buy a house in six months")
        assert intent.goal_type == "balanced"
        assert intent.interpretation is not None

    @pytest.mark.asyncio
    async def test_free_text_falls_back_when_nim_fails(self, monkeypatch):
        from backend.agents.goal import interpret

        use_client(monkeypatch, FakeClient([status_error(openai.RateLimitError, 429)]))

        intent = await interpret("I want to buy a house in six months")
        assert intent.goal_type == "balanced"
        assert intent.source == "preset"

    @pytest.mark.asyncio
    async def test_judgement_falls_back_to_deterministic_prose(self, monkeypatch):
        from backend.agents import judgement
        from backend.agents.goal import context_for, preset_intent
        from backend.models.goal import GoalType
        from tests.test_allocation import decide

        configure(monkeypatch, NVIDIA_API_KEY="")

        result = await judgement.explain(context_for("0x" + "1" * 40, "balanced", preset_intent(GoalType.BALANCED)), decide(), [])

        assert result.used_model is False
        assert result.summary
        assert result.reasoning
