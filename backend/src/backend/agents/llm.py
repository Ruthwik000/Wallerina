"""Model provider: NVIDIA NIM.

Every model call goes to NVIDIA's hosted NIM API (``integrate.api.nvidia.com``),
which speaks the OpenAI chat-completions protocol. The official ``openai``
client is used purely as a protocol library pointed at NVIDIA; nothing is sent
to OpenAI.

The model is one setting (``CHAT_MODEL``). The default, NVIDIA Nemotron 3
Super, handles the tool calling that both the chat (the what-if simulation
tool) and the agents (structured output) depend on. Any NIM chat model with
tool support can be substituted.

Structured output is obtained by forcing a single function call whose
parameters are the output schema. Models that reject a forced ``tool_choice``
are retried with ``auto``, and a JSON object in plain text is accepted as a last
resort, so the agents keep working across models.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import openai

from backend.core.config import get_settings

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """No NVIDIA API key is configured."""


class ModelError(RuntimeError):
    """A NIM call failed. The message is safe to show to the user."""


def configured() -> bool:
    return bool(get_settings().nvidia_api_key)


def model_id() -> str:
    return get_settings().chat_model


def client() -> openai.AsyncOpenAI:
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise ModelUnavailable("NVIDIA_API_KEY is not set; model calls run on NVIDIA NIM.")
    return openai.AsyncOpenAI(
        base_url=settings.nim_base_url,
        api_key=settings.nvidia_api_key,
        timeout=settings.chat_timeout_seconds,
        # One retry: a slow model otherwise leaves the user waiting minutes.
        max_retries=1,
    )


def translate(error: Exception) -> Exception:
    """Turn a client failure into a ModelError a person can act on."""
    if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
        hint = "NVIDIA rejected the API key. Check NVIDIA_API_KEY (it starts with nvapi-)."
    elif isinstance(error, openai.NotFoundError):
        hint = f"The model '{model_id()}' is not available on NVIDIA NIM. Set CHAT_MODEL to a listed model."
    elif isinstance(error, openai.RateLimitError):
        hint = "NVIDIA NIM rate limit reached; try again in a moment."
    elif isinstance(error, openai.APITimeoutError):
        hint = "NVIDIA NIM took too long to respond; try again."
    elif isinstance(error, openai.APIConnectionError):
        hint = "Could not reach NVIDIA NIM."
    elif isinstance(error, openai.APIStatusError):
        hint = f"The NVIDIA NIM request failed ({error.status_code})."
    else:
        return error

    detail = getattr(error, "message", None) or str(error)
    return ModelError(f"{hint} ({detail[:300]})")


def tool_spec(name: str, description: str, schema: dict) -> dict:
    """A chat-completions function tool definition."""
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


async def stream_chat(**kwargs: Any) -> AsyncIterator[Any]:
    """Stream chat-completion chunks from the configured model."""
    try:
        stream = await client().chat.completions.create(model=model_id(), stream=True, **kwargs)
        async for chunk in stream:
            yield chunk
    except openai.OpenAIError as error:
        raise translate(error) from error


def _json_from_text(text: str) -> dict | None:
    """Pull a JSON object out of a text reply (fenced or bare)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def structured(
    *,
    system: str,
    prompt: str,
    name: str,
    description: str,
    schema: dict,
    max_tokens: int = 1024,
) -> dict:
    """Get a JSON object matching ``schema`` via a forced function call."""
    messages = [
        {"role": "system", "content": f"{system}\n\nRespond only by calling the {name} function."},
        {"role": "user", "content": prompt},
    ]
    tools = [tool_spec(name, description, schema)]
    request = {"model": model_id(), "messages": messages, "tools": tools, "max_tokens": max_tokens, "temperature": 0.2}

    try:
        try:
            response = await client().chat.completions.create(
                **request, tool_choice={"type": "function", "function": {"name": name}}
            )
        except openai.BadRequestError:
            # Some NIM models only accept tool_choice="auto".
            response = await client().chat.completions.create(**request, tool_choice="auto")
    except openai.OpenAIError as error:
        raise translate(error) from error

    message = response.choices[0].message
    for call in message.tool_calls or []:
        if call.function.name == name:
            try:
                payload = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload

    payload = _json_from_text(message.content or "")
    if payload is not None:
        return payload

    raise ModelError("The model did not return the expected structured output.")


def describe() -> dict:
    """Provider state, for the health endpoint."""
    return {"provider": "nvidia-nim", "model": model_id(), "configured": configured()}
