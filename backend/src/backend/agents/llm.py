"""Model provider.

Inference runs on **Amazon Bedrock** by default, alongside the rest of the AWS
stack. That choice buys one concrete thing: Bedrock authenticates with the same
IAM task role as S3, SQS and RDS, so there is no separate API key to store,
rotate or leak — the ``ANTHROPIC_API_KEY`` row disappears from the deployment
entirely. Usage also lands in AWS billing and CloudWatch with everything else.

SageMaker was the alternative and is the wrong shape here: it hosts models you
bring, which would mean paying for a GPU endpoint around the clock to do two
short text tasks per analysis. Bedrock is inference-as-an-API with no capacity
to manage, which is what this workload actually needs.

The direct Anthropic API remains available via ``LLM_PROVIDER=anthropic`` for
local development without an AWS account.

Both providers are the same SDK, so call sites, prompts, structured outputs and
error types are identical — only the client construction and the model id
differ.
"""

from __future__ import annotations

import logging

import anthropic

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

BEDROCK = "bedrock"
ANTHROPIC = "anthropic"

# Bedrock namespaces model ids by vendor; the first-party API does not.
BEDROCK_PREFIX = "anthropic."


class ModelUnavailable(RuntimeError):
    """No model provider is configured."""


def provider() -> str:
    return get_settings().llm_provider.strip().lower()


def configured() -> bool:
    """Whether a model call can be attempted at all.

    Bedrock needs no key of its own: if AWS is enabled, the credential chain
    (task role, profile, or explicit keys) is expected to supply access.
    """
    settings = get_settings()

    if provider() == BEDROCK:
        return settings.aws_enabled
    return bool(settings.anthropic_api_key)


def model_id() -> str:
    """The model identifier for the active provider."""
    settings = get_settings()
    model = settings.chat_model

    if provider() == BEDROCK and not model.startswith(BEDROCK_PREFIX):
        return f"{BEDROCK_PREFIX}{model}"

    return model


def client() -> anthropic.AsyncAnthropic | anthropic.AsyncAnthropicBedrockMantle:
    """Construct the async client for the active provider."""
    settings = get_settings()

    if provider() == BEDROCK:
        if not settings.aws_enabled:
            raise ModelUnavailable(
                "LLM_PROVIDER is bedrock but AWS_ENABLED is false"
            )

        kwargs: dict = {"aws_region": settings.bedrock_region or settings.aws_region}

        # Passing nothing lets the SDK resolve the ECS task role, which is the
        # intended production path. Explicit keys are for local development.
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key"] = settings.aws_access_key_id
            kwargs["aws_secret_key"] = settings.aws_secret_access_key
            if settings.aws_session_token:
                kwargs["aws_session_token"] = settings.aws_session_token
        elif settings.aws_profile:
            kwargs["aws_profile"] = settings.aws_profile

        return anthropic.AsyncAnthropicBedrockMantle(**kwargs)

    if not settings.anthropic_api_key:
        raise ModelUnavailable("ANTHROPIC_API_KEY is not set")

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def describe() -> dict:
    """Provider state, for the health endpoint."""
    settings = get_settings()
    return {
        "provider": provider(),
        "model": model_id(),
        "configured": configured(),
        "region": settings.bedrock_region or settings.aws_region
        if provider() == BEDROCK
        else None,
    }
