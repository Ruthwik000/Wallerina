"""Judgement agent (specification section 3).

The one agent that genuinely needs a language model. Everything upstream is
deterministic; this step turns a decision that has already been made into an
explanation a person can act on.

The contract it operates under, from specification section 2: it receives the
allocation, it does not choose it. The prompt forbids altering any figure, and
the target ratio is written into the output by code — not copied from the
model's reply — so a hallucinated percentage cannot reach the user.
"""

from __future__ import annotations

import json
import logging

import anthropic

from backend.agents import llm
from backend.core.config import get_settings
from backend.models.agents import AgentReport, Judgement
from backend.models.goal import AllocationDecision, GoalIntent

logger = logging.getLogger(__name__)

SYSTEM = """\
You explain a portfolio allocation decision that has already been made by \
Wallerina's quantitative engine.

You are not deciding anything. The target allocation, the acceptable range and \
every driver below were computed before you were called. Your job is to say, in \
plain language, why the engine landed where it did.

Rules:
- Never state a percentage, dollar figure or probability that is not in the \
input. Do not round differently, recompute, or infer new numbers.
- Explain the drivers in order of size. The largest contribution is the reason; \
the rest are supporting detail.
- Do not tell the user to buy or sell a named asset, and never promise a return. \
You are explaining risk, not giving financial advice.
- If confidence is low or data is missing, say so plainly in the caveats.
- Plain prose. No markdown, no bullet characters, no emoji.

Return JSON with:
- summary: two or three sentences. What the engine concluded and the single \
biggest reason.
- reasoning: three to five strings, each one paragraph, walking through the \
drivers from largest to smallest.
- caveats: one to three strings naming real limitations of this analysis.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "reasoning": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 6,
        },
        "caveats": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 4,
        },
    },
    "required": ["summary", "reasoning", "caveats"],
    "additionalProperties": False,
}


def build_brief(
    intent: GoalIntent, decision: AllocationDecision, reports: list[AgentReport]
) -> str:
    """The facts the explainer is allowed to use. Nothing else is in scope."""
    lines: list[str] = []

    lines.append("USER GOAL")
    lines.append(f"Goal type: {intent.goal_type}")
    lines.append(f"Risk tolerance: {intent.risk_tolerance}")
    lines.append(f"Maximum acceptable drawdown: {intent.maximum_drawdown:.0%}")
    if intent.time_horizon_days:
        lines.append(f"Time horizon: {intent.time_horizon_days} days")
    if intent.interpretation:
        lines.append(f"How the goal was read: {intent.interpretation}")

    lines.append("")
    lines.append("DECISION (already made — explain, do not change)")
    lines.append(f"Target stablecoin ratio: {decision.target_stablecoin_ratio:.1%}")
    lines.append(
        f"Acceptable range: {decision.acceptable_range[0]:.1%} to "
        f"{decision.acceptable_range[1]:.1%}"
    )
    lines.append(f"Current stablecoin ratio: {decision.current_stablecoin_ratio:.1%}")
    lines.append(f"Drift from target: {decision.drift:+.1%}")
    lines.append(f"Rebalance required: {'yes' if decision.rebalance_required else 'no'}")
    lines.append(f"Engine confidence: {decision.confidence:.0%}")
    if decision.binding_constraint:
        lines.append(f"Binding constraint: {decision.binding_constraint}")
    if decision.drawdown_at_target is not None:
        lines.append(
            f"Simulated drawdown at target: {decision.drawdown_at_target:.1%}"
        )

    lines.append("")
    lines.append("DRIVERS (largest first — these are the reasons)")
    for driver in sorted(
        decision.drivers, key=lambda d: abs(d.contribution), reverse=True
    ):
        lines.append(
            f"- {driver.name}: {driver.contribution:+.1%} — {driver.detail}"
        )

    lines.append("")
    lines.append("AGENT FINDINGS")
    for report in reports:
        lines.append(f"[{report.agent}] {report.headline}")
        for finding in report.findings:
            lines.append(f"  - {finding.label} ({finding.severity}): {finding.detail}")

    return "\n".join(lines)


def _fallback(decision: AllocationDecision, reports: list[AgentReport]) -> Judgement:
    """Deterministic explanation, used when no model is available.

    Assembled from the same drivers the model would have been given, so the
    product still explains itself without an API key.
    """
    ordered = sorted(decision.drivers, key=lambda d: abs(d.contribution), reverse=True)
    principal = ordered[0] if ordered else None

    direction = "above" if decision.drift > 0 else "below"
    summary = (
        f"The engine puts the appropriate stablecoin allocation at "
        f"{decision.target_stablecoin_ratio:.0%}, against "
        f"{decision.current_stablecoin_ratio:.0%} held today — a target "
        f"{abs(decision.drift):.0%} {direction} the current position."
    )
    if principal:
        summary += f" The largest single factor is {principal.name.lower()}."

    reasoning = [f"{driver.name}: {driver.detail}." for driver in ordered[:5]]

    caveats = [
        "This explanation was generated without the language model, so it is "
        "assembled directly from the engine's drivers rather than written.",
        f"Engine confidence is {decision.confidence:.0%}; the simulation assumes "
        "zero expected return and is a risk model, not a forecast.",
    ]

    for report in reports:
        for finding in report.findings:
            if finding.severity == "high":
                caveats.append(f"{finding.label}: {finding.detail}.")
                break

    return Judgement(
        summary=summary, reasoning=reasoning, caveats=caveats[:3], used_model=False
    )


async def explain(
    intent: GoalIntent, decision: AllocationDecision, reports: list[AgentReport]
) -> Judgement:
    """Explain the allocation. Falls back to a deterministic write-up."""
    if not llm.configured():
        return _fallback(decision, reports)

    client = llm.client()
    brief = build_brief(intent, decision, reports)

    try:
        response = await client.messages.create(
            model=llm.model_id(),
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": brief}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.APIError as error:
        logger.warning("Judgement agent failed (%s); using deterministic write-up", error)
        return _fallback(decision, reports)

    for block in response.content:
        if block.type == "text":
            payload = json.loads(block.text)
            return Judgement(
                summary=payload["summary"],
                reasoning=payload["reasoning"],
                caveats=payload["caveats"],
                used_model=True,
            )

    return _fallback(decision, reports)
