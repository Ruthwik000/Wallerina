# Wallerina Backend

Data retrieval and the quantitative engine: wallet ingestion, asset
classification, risk metrics and Monte Carlo simulation.

**Implemented:** steps 1-3 and 5-10 of specification section 4 — portfolio
retrieval, classification, market and prediction-market data, risk calculation
and simulation.

**Not implemented yet (deliberately out of scope):** the goal/intent layer, the
analysis agents, the allocation engine, the judgement agent and LLM
explanation, persistence, and every AWS service. No endpoint produces a
recommendation.

## Setup

```bash
uv sync
cp .env.example .env      # add your ALCHEMY_API_KEY
uv run uvicorn backend.main:app --reload
```

Interactive API docs: http://localhost:8000/docs

```bash
uv run pytest             # 89 tests
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Liveness and configuration check |
| GET  | `/api/portfolio/{address}` | Classified, priced holdings |
| GET  | `/api/prices/history` | Daily price history by symbol or contract |
| GET  | `/api/risk/{address}` | Volatility, VaR, shortfall, drawdown, correlation |
| GET  | `/api/prediction-markets` | Active Polymarket markets for given assets |
| GET  | `/api/market-stress` | Downside signal condensed from those markets |
| POST | `/api/simulate` | Monte Carlo over the wallet's holdings |
| POST | `/api/simulate/scenarios` | Compare stablecoin ratios on identical draws |
| GET  | `/api/analysis/{address}` | Portfolio + risk + stress + simulation in one pass |
| GET  | `/api/recommendation/{address}` | Full agent pipeline → allocation + explanation |
| GET  | `/api/recommendation/{address}/history` | Past recommendations (needs RDS) |
| POST | `/api/chat` | Streaming portfolio Q&A (SSE) |

## Upstream APIs

Taken from `reference.ipynb` and re-verified against the live services.

**Alchemy** — `POST {data}/assets/tokens/by-address` for balances with metadata
and prices, and `POST {prices}/tokens/historical` for daily history (by symbol,
or by network and contract address).

Two quirks drive much of `services/wallet/alchemy.py`:

* Native tokens return a null contract address *and* null metadata, so symbol
  and decimals come from the asset registry.
* Results are **not ordered by value**. A heavily airdropped wallet returns
  thousands of spam tokens, and a low page cap silently hides real positions —
  at 5 pages one test wallet lost a $19.5M WBTC holding. The cap is 20 pages
  and `Portfolio.scan_truncated` reports when even that was not enough.

**Polymarket** — `GET {gamma}/public-search` for active events and
`GET {clob}/prices-history` for a YES token's price history. Gamma returns
`outcomes`, `outcomePrices` and `clobTokenIds` as JSON *strings* rather than
arrays, so each is parsed defensively. The YES price is read as the market's
implied probability.

Prediction markets are an optional enrichment: if the provider is unreachable
the analysis still runs, with `MarketStress.available` set to `false` and no
volatility adjustment applied.

## Asset classification

Specification section 9 requires that classification not rely on token names, so
it is driven by contract address on a known network (`assets/registry.py`).
Anything not in the registry is `unknown`, never assumed stable — but unknown
assets are counted as *volatile exposure*, since treating an unrecognised token
as safe is the one error that must not happen.

Spam is filtered before analysis: a holding must have a USD price, valid
decimals, a value above the dust threshold, and a symbol that is not an
advertisement (`"Visit liquid-eth.org claim rewards"` is a real example from the
reference wallet).

## Monte Carlo engine

`quant/monte_carlo.py` simulates the portfolio forward under correlated
geometric Brownian motion.

**Correlation.** Assets are driven by correlated shocks from the Cholesky factor
of the correlation matrix. This is the point of the model: five volatile tokens
that move together are far riskier than their position count suggests, and
independent draws would hide exactly that. Sample correlation matrices from
short windows are often not positive semi-definite, so they are repaired by
eigenvalue clipping before factorisation.

**Alignment.** Return series are aligned on **timestamps**, never on position.
Providers drop the occasional day for thinly traded tokens, and index-based
alignment slides one series against another from that point on — which silently
destroyed a real correlation estimate during development (ETH against an ETH
derivative read 0.50 instead of 0.98). There is a regression test for this.

**Drift.** By default the expected *simple* return of every asset is zero, so
the log drift is `-σ²/2`. Estimating drift from a short price history mostly
measures noise and would turn the simulator into a trend extrapolator — whatever
rose recently would be projected to keep rising. The specification is explicit
that the system does not predict prices, so a driftless market is the honest
default. `historical` and `shrunk` modes exist for explicit what-if analysis.

**Memory.** Per-asset paths are generated in batches and collapsed immediately
into a portfolio value path, so only a `(simulations, horizon + 1)` array is
retained. A 50,000 x 365 run costs roughly 150 MB instead of several GB.

**Variance reduction.** Antithetic sampling pairs each shock with its negative,
measured at roughly a 3x reduction in the standard error of the mean.

Outputs: expected/median/best/worst terminal value, 5th and 95th percentiles,
probability of loss, expected and 95th-percentile drawdown, a percentile fan
over time, and a terminal-value histogram.

### Validation

`tests/test_monte_carlo.py` checks the simulation against closed-form lognormal
results rather than just asserting stability: zero-drift runs preserve expected
value, and the median, 5th and 95th percentiles match the analytic values to
within 1-2%. It also asserts the properties the product depends on — a
correlated book has a worse 5th percentile than an independent one, and expected
drawdown falls monotonically as the stablecoin ratio rises.

## Model provider

All inference runs on **NVIDIA NIM** (`agents/llm.py`), NVIDIA's hosted,
OpenAI-compatible API at `integrate.api.nvidia.com`, authenticated with
`NVIDIA_API_KEY`. The `openai` package is used only as the protocol client;
nothing is sent to OpenAI.

The model is one setting, `CHAT_MODEL`, and defaults to Moonshot Kimi K2.6
(`moonshotai/kimi-k2.6`), which is strong at the tool calls the chat and agents
make. Any NIM chat model with tool calling can be substituted. Structured output
is obtained by forcing a single function call (retried with `tool_choice=auto`
for models that reject forcing), so it works across models.

### Why not Bedrock Agents / AgentCore

Bedrock's agent frameworks orchestrate tool use by letting the *model* decide
what to call and in what order. That is the opposite of what this system needs.
Specification section 2 requires the quantitative engine to decide the
allocation and the model only to explain it; handing orchestration to a
model-driven framework would put the model back in the decision path. The
pipeline here is deterministic control flow that calls a model twice, for the
two genuinely linguistic jobs, and that boundary is the design.

## Agents

The pipeline is `goal → rules → analysis → risk → simulation → allocation →
explanation`. Only two steps call a model:

| Step | Module | Model? |
|---|---|---|
| Goal / intent | `agents/goal.py` | Only for free text — presets resolve from a table |
| Wallet analysis | `agents/analysts.py` | No |
| Market analysis | `agents/analysts.py` | No |
| Stablecoin risk | `agents/analysts.py` | No |
| **Allocation** | `quant/allocation.py` | **Never** |
| Judgement | `agents/judgement.py` | Yes — explanation only |

Specification section 2 is the constraint that shapes this: the LLM must not
invent portfolio percentages. The allocation engine computes the target; the
judgement agent receives it and explains it. The prompt forbids restating any
figure not in its brief, and the target ratio is written into the response by
code rather than parsed from the reply, so a hallucinated number cannot reach
the user.

Every adjustment the engine makes is recorded as a named, bounded
`AllocationDriver`, and a test asserts the drivers sum to the decision — if
they didn't, the explanation would be a fiction.

The analysis agents are deterministic on purpose. No model call is needed to
observe that two assets correlate at 0.9, and using one would add latency, cost
and variance to a fact.

**With no provider configured** preset goals still work and explanations fall
back to a deterministic write-up assembled from the same drivers. Only
free-text goal parsing and model-written prose are lost.

## AWS

Every service in `docs/aws/aws_usage.md`, and every one is **optional** — with
`AWS_ENABLED=false` the application behaves exactly as it did before AWS
existed. Tests assert that degradation.

| Service | Module | Role |
|---|---|---|
| ECS / Fargate | `Dockerfile` | Container image; non-root, healthchecked |
| RDS (PostgreSQL) | `aws/database.py` | Snapshots, risk metrics, simulations, recommendation log |
| S3 | `aws/storage.py` | Historical price series and portfolio snapshots |
| Lambda | `aws/handlers.py` | Scheduled refresh jobs and the simulation worker |
| EventBridge | `aws/handlers.py` | Schedules documented per handler |
| SQS | `aws/queue.py` | Queues heavy Monte Carlo runs off the request path |
| Secrets Manager | `aws/secrets.py` | Supplies API keys; environment still wins |
| CloudWatch | `aws/telemetry.py` | Custom metrics; logs arrive via stdout |

Credentials resolve through the standard boto3 chain, so on ECS you leave the
key fields blank and the task role is used. `AWS_ENDPOINT_URL` points the whole
stack at LocalStack for local testing.

Interactive simulations stay inline; only runs above
`SIMULATION_QUEUE_THRESHOLD` (paths × horizon) are queued — offloading a
5,000-path run would add latency rather than remove it.

## Layout

```
src/backend/
  main.py                     FastAPI app and routes
  core/config.py              Settings from environment
  assets/registry.py          Trusted asset registry and classification
  models/                     Pydantic schemas
  services/
    http.py                   Shared pooled async client
    wallet/alchemy.py         Balances, prices, price history
    polymarket/client.py      Prediction markets and stress signal
    analysis.py               Orchestration: wallet -> prices -> risk -> simulation
    chat.py                   Portfolio Q&A agent (streaming, with a sim tool)
  agents/
    goal.py                   Goal/intent layer: preset table + LLM for free text
    analysts.py               Wallet, market and stablecoin analysis (deterministic)
    judgement.py              Explains the allocation; never chooses it
    pipeline.py               Runs the whole flow end to end
  quant/
    risk.py                   Returns, volatility, correlation, VaR, drawdown
    monte_carlo.py            Correlated GBM simulation engine
    allocation.py             Deterministic allocation engine
  aws/                        One module per documented AWS service
```

## Known limitations

* **Polymarket is DNS-blocked by some ISPs.** Jio, for one, returns a sinkhole
  address instead of Cloudflare. The two Polymarket hosts are therefore resolved
  over DNS-over-HTTPS (`services/dns.py`); set `POLYMARKET_DNS_OVER_HTTPS=false`
  to use system DNS.
* **The prediction-market signal is a placeholder.** `compute_market_stress`
  reduces downside markets to a bounded volatility multiplier. Distinguishing a
  10% chance of a 5% dip from a 10% chance of a 50% crash needs the market
  analysis agent, which is not built yet.
* **Volatility is historical.** A single realised-volatility estimate per asset;
  no GARCH, no implied volatility, no jumps or fat tails. Real crypto returns
  are more extreme than a lognormal, so tail estimates are, if anything,
  optimistic.
* **Persistence needs RDS.** Without `DATABASE_URL` nothing is stored, so the
  recommendation log and history endpoint are empty. The schema is created
  automatically on boot when a database is configured.
* **Only part of the AWS layer is verified live.** S3 (put/get), SQS
  (send/receive/delete) and CloudWatch metrics have been exercised against a
  real account. RDS, Secrets Manager, Lambda, EventBridge and ECS have not.
* **Allocation constants are calibrated by judgement, not fitted.** The
  reference volatility, sensitivities and caps in `quant/allocation.py` are
  reasoned defaults; they have not been backtested against historical
  outcomes.
