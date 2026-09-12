"""Goal / intent layer (specification section 6).

Two paths, deliberately:

* **Fast path** — a predefined goal maps to rules through a table. No model
  call, so no latency, no cost and no variability. The specification is
  explicit that a preset must not reach an LLM.
* **Custom path** — free text is sent to the NIM model, which extracts
  *intent only*.
  It returns a goal type, a risk tolerance and a drawdown limit; it never
  returns an allocation. The numbers still come from the table below.

That split is what keeps section 2 true: the model reads the user, the
deterministic layers decide the portfolio.
"""

from __future__ import annotations

import logging

from backend.agents import llm
from backend.models.agents import AgentContext
from backend.models.goal import (
    GoalIntent,
    GoalType,
    PortfolioRules,
    RiskTolerance,
)

logger = logging.getLogger(__name__)

# The rule table. Every goal, however it was arrived at, resolves to one of
# these rows — so a free-text goal can never produce parameters a preset
# could not.
PRESETS: dict[GoalType, dict] = {
    GoalType.AGGRESSIVE_GROWTH: {
        "risk_tolerance": RiskTolerance.HIGH,
        "base_stablecoin_ratio": 0.15,
        "minimum_stablecoin_ratio": 0.05,
        "maximum_stablecoin_ratio": 0.45,
        "maximum_drawdown": 0.35,
        "rebalance_threshold": 0.12,
        "time_horizon_days": 180,
    },
    GoalType.GROWTH: {
        "risk_tolerance": RiskTolerance.HIGH,
        "base_stablecoin_ratio": 0.25,
        "minimum_stablecoin_ratio": 0.10,
        "maximum_stablecoin_ratio": 0.55,
        "maximum_drawdown": 0.28,
        "rebalance_threshold": 0.10,
        "time_horizon_days": 180,
    },
    GoalType.BALANCED: {
        "risk_tolerance": RiskTolerance.MODERATE,
        "base_stablecoin_ratio": 0.40,
        "minimum_stablecoin_ratio": 0.25,
        "maximum_stablecoin_ratio": 0.70,
        "maximum_drawdown": 0.20,
        "rebalance_threshold": 0.10,
        "time_horizon_days": 90,
    },
    GoalType.SAVE_OVER_TIME: {
        "risk_tolerance": RiskTolerance.MODERATE,
        "base_stablecoin_ratio": 0.50,
        "minimum_stablecoin_ratio": 0.30,
        "maximum_stablecoin_ratio": 0.80,
        "maximum_drawdown": 0.15,
        "rebalance_threshold": 0.08,
        "time_horizon_days": 365,
    },
    GoalType.CAPITAL_PRESERVATION: {
        "risk_tolerance": RiskTolerance.LOW,
        "base_stablecoin_ratio": 0.65,
        "minimum_stablecoin_ratio": 0.45,
        "maximum_stablecoin_ratio": 0.90,
        "maximum_drawdown": 0.10,
        "rebalance_threshold": 0.07,
        "time_horizon_days": 365,
    },
}

# Phrases the product offers as buttons. Matched before any model call.
PRESET_PHRASES: dict[str, GoalType] = {
    "make heavy profit fast": GoalType.AGGRESSIVE_GROWTH,
    "aggressive growth": GoalType.AGGRESSIVE_GROWTH,
    "grow steadily": GoalType.GROWTH,
    "growth": GoalType.GROWTH,
    "balanced": GoalType.BALANCED,
    "save over time": GoalType.SAVE_OVER_TIME,
    "save a lot over time": GoalType.SAVE_OVER_TIME,
    "preserve capital": GoalType.CAPITAL_PRESERVATION,
    "capital preservation": GoalType.CAPITAL_PRESERVATION,
}

# The presets offered in the UI, in order of rising caution. Each label is an
# entry in PRESET_PHRASES, so choosing one never reaches the model.
PRESET_CHOICES: list[tuple[GoalType, str, str]] = [
    (GoalType.AGGRESSIVE_GROWTH, "Make heavy profit fast", "Maximum upside. Accepts large swings and deep losses."),
    (GoalType.GROWTH, "Grow steadily", "Grow the portfolio while accepting meaningful volatility."),
    (GoalType.BALANCED, "Balanced", "Growth with real protection against losses."),
    (GoalType.SAVE_OVER_TIME, "Save over time", "Accumulate steadily; losses are unwelcome."),
    (GoalType.CAPITAL_PRESERVATION, "Preserve capital", "Protecting what you already have comes first."),
]


def preset_options() -> list[dict]:
    """The preset goals with the rule-table figures behind each."""
    return [
        {
            "id": goal_type.value,
            "label": label,
            "description": description,
            "maximum_drawdown": PRESETS[goal_type]["maximum_drawdown"],
            "base_stablecoin_ratio": PRESETS[goal_type]["base_stablecoin_ratio"],
            "time_horizon_days": PRESETS[goal_type]["time_horizon_days"],
        }
        for goal_type, label, description in PRESET_CHOICES
    ]


EXTRACTION_SYSTEM = """\
You convert a person's stated financial goal into structured intent.

Return intent only. You must not decide how much of the portfolio to hold in \
stablecoins — a separate quantitative engine does that from your output.

goal_type must be exactly one of:
- aggressive_growth: wants maximum upside, accepts large losses
- growth: wants to grow the portfolio, accepts meaningful volatility
- balanced: wants growth with real protection against losses
- save_over_time: accumulating steadily, losses are unwelcome
- capital_preservation: protecting what they have is the priority

risk_tolerance must be low, moderate or high, and must agree with goal_type.

maximum_drawdown is the largest peak-to-trough loss the person would tolerate, \
as a decimal between 0.05 and 0.5. If they name a figure ("I don't want to lose \
more than 15%"), use it exactly. Otherwise infer it from the goal type.

time_horizon_days is their stated horizon in days; omit it if they gave none. \
"six months" is 180. "a house in six months" is 180.

interpretation is one short sentence, addressed to the user, saying how you \
read their goal.
"""

GOAL_SCHEMA = {
    "type": "object",
    "properties": {
        "goal_type": {
            "type": "string",
            "enum": [goal.value for goal in GoalType],
        },
        "risk_tolerance": {
            "type": "string",
            "enum": [tolerance.value for tolerance in RiskTolerance],
        },
        "maximum_drawdown": {"type": "number", "minimum": 0.05, "maximum": 0.5},
        # Omitted rather than null when no horizon was stated: not every
        # model accepts union types in a tool schema.
        "time_horizon_days": {"type": "integer", "minimum": 1},
        "interpretation": {"type": "string"},
    },
    "required": [
        "goal_type",
        "risk_tolerance",
        "maximum_drawdown",
        "interpretation",
    ],
}


def rules_for(intent: GoalIntent) -> PortfolioRules:
    """Resolve structured intent into the global rules (section 7).

    The preset row supplies every number. The only values intent may override
    are the drawdown limit and horizon, both of which the user states directly.
    """
    preset = dict(PRESETS[intent.goal_type])

    # Intent's tolerance wins: free text may express a tolerance that differs
    # from the preset row's default for that goal type.
    preset["risk_tolerance"] = intent.risk_tolerance
    preset["maximum_drawdown"] = intent.maximum_drawdown
    if intent.time_horizon_days:
        preset["time_horizon_days"] = intent.time_horizon_days

    # A tighter drawdown limit implies a higher floor: it is incoherent to
    # promise a 10% worst case while allowing a 5% stablecoin allocation.
    if intent.maximum_drawdown <= 0.12:
        preset["minimum_stablecoin_ratio"] = max(
            preset["minimum_stablecoin_ratio"], 0.40
        )
    elif intent.maximum_drawdown <= 0.20:
        preset["minimum_stablecoin_ratio"] = max(
            preset["minimum_stablecoin_ratio"], 0.20
        )

    return PortfolioRules(**preset)


def match_preset(goal: str) -> GoalType | None:
    """Fast path: does this goal correspond to a preset, verbatim?"""
    normalised = " ".join(goal.strip().lower().split())
    normalised = normalised.rstrip(".!")

    if normalised in PRESET_PHRASES:
        return PRESET_PHRASES[normalised]

    # Preset values may arrive as enum names from the UI.
    for goal_type in GoalType:
        if normalised == goal_type.value:
            return goal_type

    return None


def preset_intent(goal_type: GoalType) -> GoalIntent:
    preset = PRESETS[goal_type]
    return GoalIntent(
        goal_type=goal_type,
        risk_tolerance=preset["risk_tolerance"],
        maximum_drawdown=preset["maximum_drawdown"],
        time_horizon_days=preset["time_horizon_days"],
        source="preset",
    )


def context_for(
    address: str, goal: str, intent: GoalIntent, *, horizon_days: int | None = None
) -> AgentContext:
    """Assemble the global context from already-interpreted intent.

    A request-level horizon override is written into the rules here, once, so
    the simulator, the analysis agents and the explanation cannot disagree
    about which horizon they are reasoning over.
    """
    rules = rules_for(intent)
    if horizon_days:
        rules = rules.model_copy(update={"time_horizon_days": horizon_days})
    return AgentContext(wallet_address=address, goal=goal, intent=intent, rules=rules)


async def build_context(
    address: str, goal: str, *, horizon_days: int | None = None
) -> AgentContext:
    """The goal agent's output: the context every other agent runs under."""
    intent = await interpret(goal)
    return context_for(address, goal, intent, horizon_days=horizon_days)


async def interpret(goal: str) -> GoalIntent:
    """Turn a stated goal into structured intent.

    Falls back to the balanced preset if the model is unavailable, so a missing
    API key degrades the product rather than breaking it.
    """
    if (preset := match_preset(goal)) is not None:
        logger.info("Goal '%s' matched preset %s; no model call", goal, preset)
        return preset_intent(preset)

    if not llm.configured():
        logger.warning(
            "No model provider configured; falling back to the balanced preset"
        )
        intent = preset_intent(GoalType.BALANCED)
        intent.interpretation = (
            "Free-text goals need the language model, which is not configured. "
            "Using a balanced profile."
        )
        return intent

    try:
        payload = await llm.structured(
            system=EXTRACTION_SYSTEM,
            prompt=goal,
            name="record_goal",
            description="Record the structured intent read from the user's goal.",
            schema=GOAL_SCHEMA,
        )
        horizon = payload.get("time_horizon_days")
        return GoalIntent(
            goal_type=GoalType(payload["goal_type"]),
            risk_tolerance=RiskTolerance(payload["risk_tolerance"]),
            # Clamped: smaller models occasionally drift outside the schema.
            maximum_drawdown=min(max(float(payload["maximum_drawdown"]), 0.05), 0.5),
            time_horizon_days=int(horizon) if horizon else None,
            source="llm",
            interpretation=payload.get("interpretation"),
        )
    except (llm.ModelError, KeyError, ValueError, TypeError) as error:
        logger.warning("Goal extraction failed (%s); using balanced preset", error)
        intent = preset_intent(GoalType.BALANCED)
        intent.interpretation = "Could not interpret the goal; using a balanced profile."
        return intent
