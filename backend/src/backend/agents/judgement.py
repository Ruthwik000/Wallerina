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

import logging

from backend.agents import grounding, llm
from backend.models.agents import AgentContext, AgentReport, Judgement
from backend.models.goal import AllocationDecision

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

Record your explanation with the record_explanation tool:
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
}


def build_brief(
    context: AgentContext, decision: AllocationDecision, reports: list[AgentReport]
) -> str:
    """The facts the explainer is allowed to use. Nothing else is in scope."""
    intent, rules = context.intent, context.rules
    lines: list[str] = []

    lines.append("USER GOAL")
    lines.append(f"Stated goal: {context.goal}")
    lines.append(f"Goal type: {intent.goal_type}")
    lines.append(f"Risk tolerance: {rules.risk_tolerance}")
    lines.append(f"Maximum acceptable drawdown: {rules.maximum_drawdown:.0%}")
    lines.append(f"Time horizon: {rules.time_horizon_days} days")
    if intent.interpretation:
        lines.append(f"How the goal was read: {intent.interpretation}")

    lines.append("")
    lines.append("RULES SET BY THE GOAL (every agent worked within these)")
    lines.append(f"Base stablecoin ratio: {rules.base_stablecoin_ratio:.0%}")
    lines.append(
        f"Allowed stablecoin band: {rules.minimum_stablecoin_ratio:.0%} to "
        f"{rules.maximum_stablecoin_ratio:.0%}"
    )
    lines.append(f"Rebalance threshold: {rules.rebalance_threshold:.0%}")

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
    context: AgentContext, decision: AllocationDecision, reports: list[AgentReport]
) -> Judgement:
    """Explain the allocation, then have the grounding agent verify it.

    Falls back to the deterministic write-up when the model is unavailable,
    fails, or cites a figure the engine did not produce.
    """
    brief = build_brief(context, decision, reports)

    if not llm.configured():
        return _checked_fallback(decision, reports, brief)

    try:
        payload = await llm.structured(
            system=SYSTEM,
            prompt=brief,
            name="record_explanation",
            description="Record the explanation of the allocation decision.",
            schema=SCHEMA,
            max_tokens=2048,
        )
        reasoning = [str(item) for item in payload["reasoning"]]
        caveats = [str(item) for item in payload["caveats"]]
        if not payload["summary"] or not reasoning:
            raise ValueError("empty explanation")
        judgement = Judgement(
            summary=str(payload["summary"]),
            reasoning=reasoning,
            caveats=caveats,
            used_model=True,
        )
    except (llm.ModelError, KeyError, ValueError, TypeError) as error:
        logger.warning("Judgement agent failed (%s); using deterministic write-up", error)
        return _checked_fallback(decision, reports, brief)

    report = grounding.check(judgement.summary, *judgement.reasoning, *judgement.caveats, brief=brief)
    if report.grounded:
        judgement.grounding = report
        return judgement

    logger.warning(
        "Explanation cited figures the engine did not produce (%s); using deterministic write-up",
        ", ".join(report.rejected),
    )
    replacement = _checked_fallback(decision, reports, brief)
    replacement.grounding.replaced_model_output = True
    replacement.grounding.rejected = report.rejected
    return replacement


def _checked_fallback(
    decision: AllocationDecision, reports: list[AgentReport], brief: str
) -> Judgement:
    """The deterministic write-up, with its own grounding report attached."""
    judgement = _fallback(decision, reports)
    judgement.grounding = grounding.check(
        judgement.summary, *judgement.reasoning, *judgement.caveats, brief=brief
    )
    return judgement
