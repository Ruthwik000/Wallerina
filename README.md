<div align="center">
  <br />
    <img src="assets/banner.png" alt="Wallerina Banner">
  <br />

  <h1 align="center">Wallerina</h1>

  <div align="center">
    <strong>Dynamic crypto portfolio risk management.</strong>
    <br />
    <sub>Balance crypto exposure with stablecoin protection using real-world market signals and simulated outcomes.</sub>
  </div>

  <br />

  <div>
    <img src="https://img.shields.io/badge/Web3-000000?style=for-the-badge&logo=web3.js&logoColor=white" />
    <img src="https://img.shields.io/badge/AI_Agents-000000?style=for-the-badge&logo=openai&logoColor=white" />
    <img src="https://img.shields.io/badge/Monte_Carlo-000000?style=for-the-badge&logo=chartdotjs&logoColor=white" />
    <img src="https://img.shields.io/badge/Polymarket-000000?style=for-the-badge&logoColor=white" />
    <img src="https://img.shields.io/badge/Stablecoins-000000?style=for-the-badge&logoColor=white" />
  </div>
</div>

<br />

## 📋 <a name="table">Table of Contents</a>

1. ✨ [Introduction](#introduction)
2. 💡 [The Idea](#idea)
3. 🪙 [Why Stablecoins](#stablecoins)
4. 📊 [How Wallerina Works](#how-it-works)
5. 🔋 [Features](#features)
6. 🤸 [Quick Start](#quick-start)
7. ⚠️ [Disclaimer](#disclaimer)

---

## <a name="introduction">✨ Introduction</a>

Crypto markets can move violently in a matter of hours.

A portfolio that feels perfectly reasonable today can become heavily exposed to downside risk tomorrow. At the same time, moving everything into stablecoins whenever the market looks uncertain can mean giving up potential upside.

**Wallerina is built around this balance.**

It looks at your wallet, your financial goal, and the current market environment to determine whether your portfolio is taking an appropriate amount of risk.

Instead of relying on a permanent allocation such as `60% crypto / 40% stablecoins`, Wallerina adapts its recommendation as market conditions change.

> **The goal isn't to predict the market. It's to understand your exposure to it.**

---

## <a name="idea">💡 The Idea</a>

Imagine your portfolio currently looks like this:

```text
┌─────────────────────────────────────┐
│          YOUR PORTFOLIO             │
│                                     │
│     75% Volatile Crypto             │
│     25% Stablecoins                  │
└─────────────────────────────────────┘
```

When the market is calm, that allocation might make sense.

But suppose volatility increases and several major market events begin carrying higher probabilities.

Your portfolio hasn't changed.

**The risk around it has.**

Wallerina asks:

> **"Is the amount of risk I'm currently carrying still appropriate for my goal?"**

It then evaluates the current environment and simulates thousands of possible outcomes before producing a recommendation.

For example:

```text
Current Allocation
75% Crypto / 25% Stable

          ↓

Higher Market Risk

          ↓

Simulated Outcomes

          ↓

Recommended Allocation
55% Crypto / 45% Stable
```

The allocation is dynamic rather than permanently fixed.

*The percentages shown above are illustrative and are not financial advice.*

---

## <a name="stablecoins">🪙 Why Stablecoins?</a>

Stablecoins are crypto assets designed to maintain a relatively stable value, commonly against a fiat currency such as the US dollar.

They provide something useful for portfolio management:

> **Crypto-native liquidity without the same level of price volatility as most cryptocurrencies.**

Suppose a portfolio contains `$10,000`.

### 100% Volatile Crypto

If the crypto portion falls by 40%:

```text
$10,000
   ↓
$6,000
```

### 60% Crypto + 40% Stablecoins

If the crypto portion falls by 40%:

```text
$6,000 Crypto
$4,000 Stablecoins
        ↓
$7,600 Total
```

The stablecoin allocation doesn't eliminate losses.

It simply means that **less of the portfolio is exposed to the volatile asset movement**.

The challenge is figuring out **how much stablecoin exposure is appropriate right now**.

That's the problem Wallerina focuses on.

---

## <a name="how-it-works">📊 How Wallerina Works</a>

Wallerina combines three perspectives:

### 1. Your Portfolio

It starts with what you actually own.

```text
Wallet
  ↓
Asset Holdings
  ↓
Volatile vs Stable Exposure
  ↓
Current Portfolio Risk
```

### 2. The Market

It then looks beyond your wallet.

Market prices, historical volatility, and real-world event probabilities provide signals about the current environment.

Prediction markets are particularly useful here because they provide continuously changing probabilities around real-world events.

These probabilities are **signals**, not direct predictions of crypto prices.

### 3. Possible Futures

Instead of assuming one future, Wallerina explores thousands of them.

```text
             Current Conditions
                     │
                     ▼
            ┌─────────────────┐
            │ Risk Assessment │
            └────────┬────────┘
                     │
                     ▼
             10,000 Scenarios
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Upside      Normal     Downside
          │          │          │
          └──────────┼──────────┘
                     ▼
              Risk Distribution
                     │
                     ▼
             Portfolio Action
```

This allows the system to reason about **the range of outcomes**, rather than pretending it knows exactly what will happen.

---

## <a name="features">🔋 Features</a>

👉 **Dynamic Stablecoin Allocation**
Get a recommended balance between volatile crypto and stablecoins based on your current risk environment instead of relying on a fixed ratio.

👉 **Goal-Aware Recommendations**
Your desired outcome matters. A portfolio optimized for aggressive growth shouldn't be treated the same as one designed around capital preservation.

👉 **Real-World Market Signals**
Prediction-market probabilities provide additional context around upcoming economic, regulatory, and crypto-related events.

👉 **Monte Carlo Risk Simulation**
Thousands of possible market scenarios are evaluated to understand potential portfolio drawdowns and downside exposure.

👉 **Portfolio Risk Analysis**
Understand how much of your current portfolio is exposed to volatile assets and how that exposure changes under different scenarios.

👉 **Actionable Recommendations**
Instead of overwhelming you with charts and metrics, Wallerina translates its analysis into a clear portfolio action.

👉 **Transparent Reasoning**
Every recommendation comes with an explanation of the major factors that influenced it.

👉 **Risk-Aware Stablecoin Selection**
Stablecoins aren't treated as universally risk-free. Their liquidity and stability can also become part of the decision.

👉 **Human-Controlled Decisions**
The system is designed to inform and recommend rather than blindly moving funds on your behalf.


---

## 🧠 The Philosophy

Wallerina isn't built around the idea that an AI can tell you exactly what the market will do next.

Markets are uncertain.

The better question is:

> **"Given what we know right now, how much uncertainty can my portfolio afford?"**

Wallerina tries to answer that question by combining your goals, your current exposure, market signals, and thousands of possible scenarios.

**Not prediction.
Not panic.
Not a fixed ratio.**

**Adaptive risk management.**


