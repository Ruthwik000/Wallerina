> **Status: superseded, kept as the record of intent.**
>
> This was the specification written before the backend existed. It stops
> mid-sentence in section 10 — sections 10 to 16 were never written — yet the
> code they would have described is built and tested. Finishing it now would be
> documenting the past against the present.
>
> It is frozen here because the decisions in sections 1 to 9 still govern the
> system and are cited throughout the code: the DATA -> QUANT -> RISK ->
> ALLOCATION -> EXPLANATION separation (section 2), the preset fast path
> (section 6), the global rules (section 7), and the rule that an unrecognised
> asset is never assumed stable (section 9). Those are live constraints, not
> history.
>
> For what the system does **now**, read:
>
> * `../../context.md` — current state, stack and decisions
> * `../../backend/README.md` — architecture, endpoints and known limitations
> * `../../todo.md` — what is next
>
> Do not add to this file. Record new decisions in the root `context.md`.

---

# Wallerina Backend Specification

## 1. Project Context

Wallerina is a Web3 portfolio risk-management system designed to help users dynamically manage their exposure between volatile crypto assets and stablecoins.

The core problem is simple:

A crypto portfolio can become excessively exposed to volatile assets during periods of elevated market risk. A fixed allocation such as 60% crypto / 40% stablecoins may work under one market condition but become inappropriate when volatility, market sentiment, or external events change.

Wallerina therefore evaluates:

* The user's current wallet composition
* The user's financial goal
* Current and historical market behavior
* Prediction-market probabilities
* Stablecoin-specific conditions
* Portfolio volatility and drawdown
* Simulated future outcomes

The system produces a **target allocation range** and, when appropriate, a **recommended rebalance**.

The system does not attempt to predict the exact future price of an asset.

Its purpose is to answer:

> **"Given the user's goal, current portfolio, and available market information, how much exposure to volatile assets is appropriate under the current risk environment?"**

---

# 2. Core Design Principle

The backend must separate:

```text
DATA
  ↓
QUANTITATIVE ANALYSIS
  ↓
RISK MODEL
  ↓
ALLOCATION DECISION
  ↓
AI EXPLANATION
```

The LLM must **not independently invent portfolio percentages**.

For example, the LLM should never be responsible for deciding:

```text
"Hold 43% stablecoins."
```

Instead, the quantitative allocation engine calculates:

```json
{
  "target_stablecoin_ratio": 0.43,
  "acceptable_range": [0.38, 0.48],
  "confidence": 0.81
}
```

The LLM then explains why the system reached that conclusion.

This separation is fundamental to the architecture.

---

# 3. High-Level Backend Architecture

```text
                         USER
                           │
                           │
                    Wallet + Goal
                           │
                           ▼
                 ┌──────────────────┐
                 │ API / Controller │
                 └────────┬─────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │ Goal / Intent Layer │
                └──────────┬──────────┘
                           │
                    Global Risk Rules
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
   Wallet Analysis    Market Analysis   Stablecoin
       Agent              Agent        Risk Analysis
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                 ┌─────────────────────┐
                 │ Quantitative Risk   │
                 │      Engine         │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Monte Carlo Engine  │
                 └──────────┬──────────┘
                            │
                    Scenario Results
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Allocation Engine   │
                 └──────────┬──────────┘
                            │
                     Target Allocation
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Judgement Agent     │
                 │ + Explanation LLM   │
                 └──────────┬──────────┘
                            │
                            ▼
                 Recommendation Payload
                            │
                            ▼
                         FRONTEND
```

---

# 4. Backend Responsibilities

The backend is responsible for:

1. Receiving wallet and goal information.
2. Retrieving portfolio balances.
3. Classifying assets into volatile and stable-value categories.
4. Processing user goals.
5. Fetching market data.
6. Fetching prediction-market data.
7. Calculating quantitative market metrics.
8. Evaluating stablecoin risk.
9. Running Monte Carlo simulations.
10. Calculating portfolio risk.
11. Determining a target allocation.
12. Detecting whether rebalancing is necessary.
13. Generating an explanation.
14. Returning structured recommendations to the frontend.
15. Maintaining historical analysis where necessary.
16. Logging every recommendation and its supporting inputs.

The backend should initially be **recommendation-only**.

Actual blockchain transactions should be a separate execution layer and should require explicit user approval.

---

# 5. User Input

The primary input is:

```json
{
  "wallet_address": "0x...",
  "goal": "Save a lot over time"
}
```

The wallet address is used to determine the user's current portfolio.

The goal describes the user's desired financial behavior.

Goals may be:

### Predefined

Examples:

```text
Make heavy profit fast
Grow steadily
Preserve capital
Save over time
```

### Custom

Examples:

```text
I want to save for a house in six months.
```

```text
I am willing to take high risk for long-term growth.
```

```text
I don't want to lose more than 15% of my portfolio.
```

---

# 6. Goal / Intent Layer

The goal layer converts natural-language user intent into structured rules.

## Fast Path

If the user selects a predefined goal, do not call an LLM.

Use a deterministic mapping.

Example:

```json
{
  "goal_type": "aggressive_growth",
  "risk_tolerance": "high",
  "base_stablecoin_ratio": 0.15,
  "maximum_drawdown": 0.30
}
```

This reduces:

* Latency
* Cost
* Unnecessary model calls
* Variability

## Custom Goal

If the user provides free-form text, use an LLM to convert it into structured parameters.

Example:

```text
"I want to preserve most of my money and avoid large losses."
```

becomes:

```json
{
  "goal_type": "capital_preservation",
  "risk_tolerance": "low",
  "maximum_drawdown": 0.10,
  "time_horizon": null
}
```

The LLM should extract intent, not directly determine the final allocation.

---

# 7. Global Portfolio Rules

The goal layer produces global rules consumed by downstream components.

Example:

```json
{
  "risk_tolerance": "moderate",
  "base_stablecoin_ratio": 0.40,
  "minimum_stablecoin_ratio": 0.25,
  "maximum_stablecoin_ratio": 0.70,
  "maximum_drawdown": 0.20,
  "rebalance_threshold": 0.10,
  "time_horizon_days": 30
}
```

These values act as constraints for the quantitative engine.

The final allocation must remain within the user's allowed risk boundaries.

---

# 8. Wallet / Portfolio Analysis

The backend must obtain the user's current wallet holdings.

The wallet layer should determine:

* Asset
* Quantity
* Current price
* USD value
* Portfolio percentage
* Asset classification
* Chain
* Contract address where applicable

Example:

```json
{
  "assets": [
    {
      "symbol": "ETH",
      "quantity": 2.4,
      "value_usd": 7200,
      "portfolio_ratio": 0.60,
      "classification": "volatile"
    },
    {
      "symbol": "USDC",
      "quantity": 3000,
      "value_usd": 3000,
      "portfolio_ratio": 0.25,
      "classification": "stablecoin"
    }
  ]
}
```

The portfolio analyzer then calculates:

```text
volatile exposure
stablecoin exposure
asset concentration
portfolio value
portfolio volatility
portfolio drawdown
correlation exposure
```

---

# 9. Asset Classification

The system must distinguish between:

### Volatile Assets

Examples:

* BTC
* ETH
* SOL
* Other non-stable crypto assets

### Stablecoins

Examples:

* USDC
* USDT
* Other supported stable-value tokens

The classification should not rely solely on token names.

Asset metadata should ideally be maintained through a trusted asset registry.

Unknown assets should be classified as:

```text
unknown
```

rather than being incorrectly treated as stablecoins.

---

# 10. Market Data Layer

The market data layer provides historical and current information.
