"""Grounding agent: every figure in an explanation must come from the engine.

Specification section 2: the model explains, it never produces numbers. The
judgement prompt says so, but a prompt is a request, not a guarantee. This agent
enforces it after the fact. It extracts every percentage and dollar amount from
the model's text and checks each one against the figures in the brief the model
was given. A figure it cannot match is ungrounded, and the explanation is
rejected in favour of the deterministic write-up.

Matching allows for honest rounding (80.4% written as 80%, $40,700 as $40.7k)
and ignores sign, since "a 5% drop" and "-5%" describe the same figure.
"""

from __future__ import annotations

import re

from backend.models.agents import GroundingReport

PERCENT = re.compile(r"(?<![\w.])[+\-−]?(\d+(?:\.(\d+))?)\s?(?:%|percent\b)", re.I)
DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(k|bn|b|m|thousand|million|billion)?\b", re.I)
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}

# Relative slack for dollar amounts written in rounded or abbreviated form.
DOLLAR_TOLERANCE = 0.01


def _percentages(text: str) -> list[tuple[str, float, int]]:
    return [
        (match.group(0).strip(), float(match.group(1)), len(match.group(2) or ""))
        for match in PERCENT.finditer(text)
    ]


def _dollars(text: str) -> list[tuple[str, float]]:
    figures = []
    for match in DOLLARS.finditer(text):
        value = float(match.group(1).replace(",", ""))
        suffix = (match.group(2) or "").lower()
        figures.append((match.group(0).strip(), value * MULTIPLIERS.get(suffix, 1.0)))
    return figures


def check(*texts: str, brief: str) -> GroundingReport:
    """Check every figure in ``texts`` against the figures in ``brief``."""
    allowed_percent = [value for _, value, _ in _percentages(brief)]
    allowed_dollars = [value for _, value in _dollars(brief)]

    checked = 0
    rejected: list[str] = []

    for text in texts:
        for raw, value, decimals in _percentages(text):
            checked += 1
            # A figure written to fewer decimals can be off by half its last
            # digit; the extra 0.051 absorbs the source's own rounding.
            tolerance = 0.5 * 10**-decimals + 0.051
            if not any(abs(value - allowed) <= tolerance for allowed in allowed_percent):
                rejected.append(raw)

        for raw, value in _dollars(text):
            checked += 1
            if not any(
                abs(value - allowed) <= max(1.0, allowed * DOLLAR_TOLERANCE)
                for allowed in allowed_dollars
            ):
                rejected.append(raw)

    unique = list(dict.fromkeys(rejected))
    return GroundingReport(grounded=not unique, figures_checked=checked, rejected=unique)
