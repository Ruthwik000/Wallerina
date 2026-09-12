"""Portfolio chat agent.

Answers questions about a specific wallet. The model is given the already
computed quantitative snapshot as context and one tool for running fresh
what-if simulations, so it explains and explores the engine's numbers rather
than inventing its own.

This keeps the specification's core separation intact: the quantitative engine
decides the numbers, the model explains them. The system prompt states that
constraint explicitly, and the only way for the model to obtain a new figure is
to call the simulation tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from backend.agents import llm
from backend.core.config import get_settings
from backend.models.portfolio import Portfolio
from backend.models.quant import RiskMetrics, SimulationResult
from backend.services import analysis
from backend.services.analysis import EstimationResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Wallerina, an assistant that explains a specific crypto wallet's risk \
position to its owner.

Your role is to interpret numbers that have already been computed by \
Wallerina's quantitative engine. You never invent portfolio figures. If you \
need a number that is not in the context below — for example the outcome of a \
different allocation — call the `run_simulation` tool and use what it returns. \
If a figure is genuinely unavailable, say so plainly.

How to answer:
- Be direct and concrete. Lead with the answer, then the reasoning.
- Quote the actual numbers from the context, with their units.
- Explain what a metric means when you use it. The user may not know what \
expected shortfall or a 5th percentile outcome is.
- Keep responses short — usually two to five sentences. Expand only when the \
question genuinely needs it.
- Plain text only. No markdown headers, no bullet characters, no emoji.

Important limits you must respect:
- You are not a licensed financial adviser and must not tell the user to buy \
or sell any specific asset, or promise any return. You may explain what the \
engine's analysis shows and what a given allocation would imply for risk.
- The simulation assumes zero expected return by default. It is a risk model, \
not a price forecast. Never present a simulated value as a prediction.
- Unrecognised tokens are classified "unknown" and counted as volatile. Say so \
if the user asks why something is categorised the way it is.
"""

SIMULATION_TOOL: dict[str, Any] = llm.tool_spec(
    "run_simulation",
    (
        "Run a fresh Monte Carlo simulation on this wallet under a different "
        "allocation or time horizon. Use this for any 'what if' question — for "
        "example what happens if the user moves half the book into stablecoins, "
        "or how the risk looks over a year instead of 90 days. Returns expected, "
        "median and percentile outcomes, probability of loss, and expected "
        "drawdown."
    ),
    {
        "type": "object",
        "properties": {
            "stablecoin_ratio": {
                "type": "number",
                "description": (
                    "Target share of the portfolio held in stablecoins, 0 to 1. "
                    "Omit to keep the wallet's current allocation."
                ),
                "minimum": 0,
                "maximum": 1,
            },
            "horizon_days": {
                "type": "integer",
                "description": "Simulation horizon in days, 1 to 1095.",
                "minimum": 1,
                "maximum": 1095,
            },
        },
        "required": [],
    },
)


class ChatUnavailableError(RuntimeError):
    """The chat agent is not configured."""


def _require_model() -> None:
    if not llm.configured():
        raise ChatUnavailableError(
            "The portfolio chat runs on NVIDIA NIM, which needs NVIDIA_API_KEY."
        )


def build_context(
    portfolio: Portfolio,
    risk: RiskMetrics,
    simulation: SimulationResult,
    excluded: list[str],
) -> str:
    """Render the quantitative snapshot the model reasons over.

    Written as plain labelled text rather than raw JSON: it is markedly easier
    for the model to quote accurately, and cheaper in tokens.
    """
    lines: list[str] = []

    lines.append("PORTFOLIO")
    lines.append(f"Wallet: {portfolio.address}")
    lines.append(f"Total value: ${portfolio.total_value_usd:,.2f}")
    lines.append(
        f"Stablecoin allocation: {portfolio.stablecoin_ratio:.2%} "
        f"(${portfolio.stablecoin_value_usd:,.2f})"
    )
    lines.append(f"Volatile allocation: {portfolio.volatile_ratio:.2%}")
    lines.append(
        f"Concentration (HHI, 1.0 = single asset): {portfolio.concentration:.3f}"
    )
    if portfolio.scan_truncated:
        lines.append(
            "NOTE: the wallet holds more tokens than were scanned, so totals "
            "may be understated."
        )

    lines.append("")
    lines.append("HOLDINGS (symbol, chain, class, value, share of book)")
    for holding in portfolio.holdings[:25]:
        lines.append(
            f"- {holding.symbol} | {holding.chain} | {holding.classification} | "
            f"${holding.value_usd:,.2f} | {holding.portfolio_ratio:.2%}"
        )
    if len(portfolio.holdings) > 25:
        lines.append(f"- ...and {len(portfolio.holdings) - 25} smaller positions")

    lines.append("")
    lines.append("RISK (from daily history)")
    lines.append(
        f"Annualised volatility: {risk.portfolio_annual_volatility:.2%}"
    )
    lines.append(
        f"Value at Risk ({risk.confidence:.0%}, 1 day): {risk.value_at_risk:.2%} "
        f"(${risk.value_at_risk_usd:,.2f})"
    )
    lines.append(
        f"Expected shortfall (mean loss beyond VaR): {risk.expected_shortfall:.2%} "
        f"(${risk.expected_shortfall_usd:,.2f})"
    )
    lines.append(f"Worst historical drawdown: {risk.max_drawdown:.2%}")
    lines.append(f"Observations used: {risk.observations} days")

    lines.append("")
    lines.append("RISK CONTRIBUTION BY ASSET (share of total portfolio risk)")
    for asset in risk.assets[:12]:
        lines.append(
            f"- {asset.symbol}: {asset.risk_contribution:.2%} of risk, "
            f"weight {asset.weight:.2%}, volatility {asset.annual_volatility:.1%}, "
            f"beta {asset.beta_to_portfolio:.2f}"
        )

    pairs = _notable_correlations(risk)
    if pairs:
        lines.append("")
        lines.append("NOTABLE CORRELATIONS (90+ day daily returns)")
        lines.extend(pairs)

    lines.append("")
    lines.append(
        f"SIMULATION ({simulation.simulations:,} paths, "
        f"{simulation.horizon_days} days, zero-drift assumption)"
    )
    lines.append(f"Starting value: ${simulation.initial_value:,.2f}")
    lines.append(f"Expected value: ${simulation.expected_value:,.2f}")
    lines.append(f"Median value: ${simulation.median_value:,.2f}")
    lines.append(
        f"5th percentile (bad case): ${simulation.p5:,.2f} — "
        f"95% of simulated paths ended above this"
    )
    lines.append(f"95th percentile (good case): ${simulation.p95:,.2f}")
    lines.append(f"Probability of ending below today: {simulation.probability_of_loss:.2%}")
    lines.append(f"Expected peak-to-trough drawdown: {simulation.expected_drawdown:.2%}")
    lines.append(
        f"Drawdown exceeded by only 5% of paths: {simulation.max_drawdown_p95:.2%}"
    )

    if excluded:
        lines.append("")
        lines.append(
            "EXCLUDED FROM ANALYSIS (insufficient price history): "
            + ", ".join(excluded)
        )

    return "\n".join(lines)


def _notable_correlations(risk: RiskMetrics, threshold: float = 0.6) -> list[str]:
    """Surface only strongly correlated pairs; a full matrix is mostly noise."""
    symbols = risk.correlation_symbols
    matrix = risk.correlation_matrix
    pairs: list[tuple[float, str]] = []

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            value = matrix[i][j]
            if abs(value) >= threshold:
                pairs.append((abs(value), f"- {symbols[i]} / {symbols[j]}: {value:+.2f}"))

    pairs.sort(reverse=True)
    return [text for _, text in pairs[:10]]


async def _run_simulation_tool(
    estimate: EstimationResult, tool_input: dict
) -> dict:
    """Execute the what-if simulation the model asked for."""
    settings = get_settings()

    horizon = int(tool_input.get("horizon_days") or settings.default_horizon_days)
    horizon = max(1, min(horizon, settings.max_horizon_days))

    ratio = tool_input.get("stablecoin_ratio")
    if ratio is not None:
        ratio = float(ratio)
        # Some models send a percentage (50) where a fraction (0.5) is asked for.
        if ratio > 1:
            ratio /= 100
        ratio = max(0.0, min(ratio, 1.0))
        if not estimate.stable_mask.any():
            return {
                "error": (
                    "This wallet holds no recognised stablecoin, so capital "
                    "cannot be rotated into one in the simulation."
                )
            }

    result = analysis.run_simulation(
        estimate,
        estimate.total_value,
        horizon_days=horizon,
        simulations=5_000,  # smaller than the page default; this is interactive
        seed=7,             # fixed, so repeating a question gives a stable answer
        stablecoin_ratio=ratio,
    )

    return {
        "stablecoin_ratio": round(result.stablecoin_ratio, 4),
        "horizon_days": result.horizon_days,
        "starting_value_usd": round(result.initial_value, 2),
        "expected_value_usd": round(result.expected_value, 2),
        "median_value_usd": round(result.median_value, 2),
        "p5_usd": round(result.p5, 2),
        "p95_usd": round(result.p95, 2),
        "probability_of_loss": round(result.probability_of_loss, 4),
        "expected_drawdown": round(result.expected_drawdown, 4),
        "drawdown_p95": round(result.max_drawdown_p95, 4),
    }


def _normalise(question: str) -> str:
    return " ".join(re.sub(r"[?!.,]", " ", question.lower()).split())


def _value(field: object) -> str:
    return str(getattr(field, "value", field))


def _volatility_label(volatility: float) -> str:
    if volatility < 0.3:
        return "low"
    if volatility < 0.6:
        return "moderate"
    if volatility < 1.0:
        return "high"
    return "very high"


def _answer_how_risky(portfolio, risk, simulation, estimate) -> str:
    return (
        f"Your portfolio is worth ${portfolio.total_value_usd:,.2f} and its risk is "
        f"{_volatility_label(risk.portfolio_annual_volatility)}: annualised volatility is "
        f"{risk.portfolio_annual_volatility:.0%}. Value at Risk at {risk.confidence:.0%} "
        f"confidence is {risk.value_at_risk:.2%} (${risk.value_at_risk_usd:,.2f}), meaning "
        f"on all but the worst {1 - risk.confidence:.0%} of days you would lose less than that "
        f"in a single day; when losses do exceed it they average {risk.expected_shortfall:.2%} "
        f"(the expected shortfall). The worst historical peak-to-trough fall was "
        f"{risk.max_drawdown:.2%}. Over the next {simulation.horizon_days} days the simulation "
        f"gives a {simulation.probability_of_loss:.0%} chance of ending below today, with an "
        f"expected drawdown of {simulation.expected_drawdown:.1%} along the way. "
        f"{portfolio.stablecoin_ratio:.0%} of the book is in stablecoins."
    )


def _answer_top_risk(portfolio, risk, simulation, estimate) -> str:
    if not risk.assets:
        return "There is not enough price history to attribute risk to individual assets yet."

    ordered = sorted(risk.assets, key=lambda asset: asset.risk_contribution, reverse=True)
    top = ordered[0]
    answer = (
        f"{top.symbol} contributes the most risk: {top.risk_contribution:.0%} of total portfolio "
        f"risk while making up {top.weight:.0%} of its value. Risk contribution combines size "
        f"with how volatile the asset is ({top.annual_volatility:.0%} a year) and how much it "
        f"moves with the rest of the book (beta {top.beta_to_portfolio:.2f})"
    )
    if top.risk_contribution > top.weight:
        answer += ", so it adds more risk than its share of value alone would suggest."
    else:
        answer += "."
    if len(ordered) > 1:
        second = ordered[1]
        answer += (
            f" Next is {second.symbol} at {second.risk_contribution:.0%} of risk "
            f"for {second.weight:.0%} of value."
        )
    return answer


async def _answer_half_stable(portfolio, risk, simulation, estimate) -> str:
    result = await _run_simulation_tool(
        estimate, {"stablecoin_ratio": 0.5, "horizon_days": simulation.horizon_days}
    )
    if "error" in result:
        return result["error"]

    return (
        f"Moving to 50% stablecoins (from {portfolio.stablecoin_ratio:.0%} today), over "
        f"{simulation.horizon_days} days: the bad-case outcome (5th percentile) goes from "
        f"${simulation.p5:,.2f} to ${result['p5_usd']:,.2f}; the chance of ending below today "
        f"goes from {simulation.probability_of_loss:.0%} to {result['probability_of_loss']:.0%}; "
        f"and the expected drawdown goes from {simulation.expected_drawdown:.1%} to "
        f"{result['expected_drawdown']:.1%}. The simulation assumes zero expected return, so "
        f"this shows how much risk the switch removes, not a forecast of gains or losses."
    )


def _answer_p5(portfolio, risk, simulation, estimate) -> str:
    loss = simulation.initial_value - simulation.p5
    return (
        f"Your 5th percentile outcome is ${simulation.p5:,.2f} after {simulation.horizon_days} "
        f"days, starting from ${simulation.initial_value:,.2f}. Out of {simulation.simulations:,} "
        f"simulated futures, 95% ended above that value and only the worst 5% ended below it — "
        f"so it is a realistic bad case, a loss of about ${loss:,.2f}, not the worst case. "
        f"For comparison the median outcome is ${simulation.median_value:,.2f}. It is a risk "
        f"measure, not a prediction."
    )


def _answer_unknown(portfolio, risk, simulation, estimate) -> str:
    unknown = [holding for holding in portfolio.holdings if _value(holding.classification) == "unknown"]
    if not unknown:
        return (
            "None of your current holdings is classified as unknown. A token is marked unknown "
            "when it is not in Wallerina's trusted asset registry; it is then counted as "
            "volatile, because an unrecognised token cannot be assumed to hold its value."
        )

    names = ", ".join(f"{holding.symbol} (${holding.value_usd:,.2f})" for holding in unknown[:8])
    return (
        f"These holdings are classified as unknown: {names}. A token is marked unknown when it "
        f"is not in Wallerina's trusted asset registry — matching on contract address, not just "
        f"the symbol, because symbols are easy to impersonate. Unknown tokens are counted as "
        f"volatile, since an unrecognised token cannot be assumed to hold its value."
    )


# The questions the chat UI offers as suggestions (frontend Chat.js).
PRESET_QUESTIONS = {
    _normalise("How risky is my portfolio right now?"): _answer_how_risky,
    _normalise("Which asset contributes the most risk, and why?"): _answer_top_risk,
    _normalise("What would happen if I moved half of it into stablecoins?"): _answer_half_stable,
    _normalise("What does my 5th percentile outcome actually mean?"): _answer_p5,
    _normalise("Why is one of my tokens classified as unknown?"): _answer_unknown,
}


async def preset_answer(message, portfolio, risk, simulation, estimate) -> str | None:
    """Answer a suggested question from computed figures, or None."""
    handler = PRESET_QUESTIONS.get(_normalise(message))
    if handler is None:
        return None

    answer = handler(portfolio, risk, simulation, estimate)
    if asyncio.iscoroutine(answer):
        answer = await answer
    logger.info("Chat question matched a preset; no model call")
    return answer


def trim_history(history: list[dict]) -> list[dict]:
    """Keep the conversation bounded, and always start on a user turn."""
    settings = get_settings()
    trimmed = history[-settings.chat_max_history :]

    while trimmed and trimmed[0].get("role") != "user":
        trimmed.pop(0)

    return trimmed


async def stream_reply(
    *,
    message: str,
    history: list[dict],
    portfolio: Portfolio,
    risk: RiskMetrics,
    simulation: SimulationResult,
    estimate: EstimationResult,
    excluded: list[str],
) -> AsyncIterator[dict]:
    """Stream the assistant's reply, running tool calls as they are requested.

    Yields event dicts for the transport layer to serialise:
      {"type": "text", "text": ...}    incremental response text
      {"type": "tool", "name": ...}    a tool call started (for UI feedback)
      {"type": "error", "message": ...}
      {"type": "done"}
    """
    # Fast path: the suggested questions are answered straight from the
    # engine's figures, with no model call — like goal presets.
    preset = await preset_answer(message, portfolio, risk, simulation, estimate)
    if preset is not None:
        yield {"type": "text", "text": preset}
        yield {"type": "done"}
        return

    _require_model()
    settings = get_settings()

    context = build_context(portfolio, risk, simulation, excluded)

    messages: list[dict] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\nCurrent analysis for this wallet:\n\n{context}"},
        *to_messages(trim_history(history)),
        {"role": "user", "content": message},
    ]

    try:
        # Loop so the model can call the simulation tool and then answer with
        # the result. Two rounds is ample for a single what-if question.
        for _ in range(3):
            text = ""
            tool_calls: dict[int, dict] = {}
            finish_reason = None

            async for chunk in llm.stream_chat(
                messages=messages,
                tools=[SIMULATION_TOOL],
                tool_choice="auto",
                max_tokens=settings.chat_max_tokens,
            ):
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    text += delta.content
                    yield {"type": "text", "text": delta.content}

                for call in delta.tool_calls or []:
                    entry = tool_calls.setdefault(call.index, {"id": None, "name": "", "arguments": ""})
                    if call.id:
                        entry["id"] = call.id
                    if call.function and call.function.name:
                        entry["name"] = call.function.name
                    if call.function and call.function.arguments:
                        entry["arguments"] += call.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            # Some models end a tool-calling turn with "stop"; the presence of
            # calls is what matters.
            if not tool_calls:
                break

            ordered = [tool_calls[index] for index in sorted(tool_calls)]
            for position, call in enumerate(ordered):
                call["id"] = call["id"] or f"call_{position}"

            messages.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                        }
                        for call in ordered
                    ],
                }
            )

            for call in ordered:
                try:
                    arguments = json.loads(call["arguments"]) if call["arguments"].strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}

                yield {"type": "tool", "name": call["name"]}
                logger.info("Chat tool call: %s %s (finish=%s)", call["name"], arguments, finish_reason)

                if call["name"] == "run_simulation":
                    output = await _run_simulation_tool(estimate, arguments)
                else:
                    output = {"error": f"Unknown tool {call['name']}"}

                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output)})

    except ChatUnavailableError:
        raise
    except llm.ModelError as error:
        logger.error("NIM chat call failed: %s", error)
        yield {"type": "error", "message": str(error)}

    yield {"type": "done"}


def to_messages(history: list[dict]) -> list[dict]:
    """Plain {role, content} turns, cleaned for the chat-completions API.

    Blank turns are dropped and adjacent same-role turns merged, and history
    must end on an assistant turn because the new user message follows it.
    """
    messages: list[dict] = []
    for item in history:
        text = (item.get("content") or "").strip()
        if not text:
            continue
        if messages and messages[-1]["role"] == item["role"]:
            messages[-1]["content"] += f"\n\n{text}"
        else:
            messages.append({"role": item["role"], "content": text})

    if messages and messages[-1]["role"] == "user":
        messages.pop()
    return messages
