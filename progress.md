# Wallerina: Progress

Session record — what changed, what is next, what is blocked.

**Written 2026-09-13.** Companion to the other two root documents, not a
replacement: `context.md` holds the current state and the decisions behind it,
`todo.md` holds the working task list. This file is the narrative of the last
two sessions and the honest status of everything outstanding.

**Test suite: 335 passing, 0 failing.**
Started this session at 267 passing / 1 failing.

```
267 + 1 failing   where the session began
268               $5-leg boundary fixed
301               quant/implied.py and its tests
312               analysis wiring, 24h window, scan_truncated test
335               Kalshi client, fixtures and tests
```

---

# Part 1 — What was done

## 1.1 The failing test, resolved

`tests/test_execution.py` had one failure, outstanding and undecided.

**Cause.** In `services/execution.py::build_legs`, a $30 native ETH position on
mainnet less the $25 gas reserve leaves exactly $5.00, and the guard read
`if amount_usd < MIN_LEG_USD` — `5.0 < 5.0` is false, so a $5 leg was built.
The test expected none.

**Decision: the code was wrong, not the test.** `MIN_LEG_USD`'s own docstring
says a swap this small costs more in gas and slippage than it moves; at exactly
$5 on Ethereum mainnet, gas alone exceeds the trade. The boundary is now
exclusive.

Four lines changed — the constant's comment and all three comparisons, so the
rule reads identically everywhere it is applied:

```python
MIN_LEG_USD = 5.0
if remaining   <= MIN_LEG_USD: break        # was <
if amount_usd  <= MIN_LEG_USD: continue     # was <    the fix
if remaining    > MIN_LEG_USD:              # was >=   the "no executable
                                            #          position" note
```

## 1.2 Market-implied volatility — the substantive change

This is the work that changes what the product knows.

**The problem.** `compute_market_stress` took every downside prediction market,
averaged the probabilities weighted by liquidity, and collapsed the result into
one multiplier between 1.0 and 1.5. The *threshold* was discarded, so
`P(ETH <= $800) = 2.25%` and `P(ETH <= $1,500) = 14%` entered as the same fact.
The README already called this "an intentionally simple stand-in".

**What the data actually is.** Each downside market is a point on a cumulative
distribution, and each upside market is `1 - p` on the same curve. A family of
them at one expiry is a market-implied CDF, priced by people with money at
risk. Seven live ETH markets at 31 December 2026:

| Level | P(X <= level) | From |
|---|---|---|
| $800 | 2.25% | dip |
| $1,000 | 6.50% | dip |
| $1,500 | 14.00% | dip |
| $6,000 | 95.70% | reach |
| $7,500 | 97.15% | reach |
| $8,000 | 97.85% | reach |
| $10,000 | 98.55% | reach |

Monotonic, zero violations, the deepest market carrying $2.6M of volume.

**What was built.** `quant/implied.py` fits one lognormal per asset per expiry,
consistent with the simulator's zero-drift convention so volatility is the only
free parameter:

```text
P(S_T <= K) = Phi( ( ln(K / S_0) + sigma^2 T / 2 ) / ( sigma sqrt(T) ) )
```

ETH fits at **99.5% annualised** against the engine's 55% reference, rmse 0.014.
A 40,000-path run through the real Monte Carlo engine reproduces the market's
own probabilities at every quoted level.

**The finding underneath it:** the simulator had been running ETH at roughly
half the volatility the market was pricing.

**Guards, each with a test.** Expiry is the grouping key, not a refinement —
two expiries are two random variables. A decreasing curve is repaired to its
running maximum (the standard isotonic fix for a stale quote on a thin book),
the repair count is carried, and a curve needing more than 25% repair is
refused. Fewer than three points is interpolation, not estimation. A fit pinned
to a volatility bound is discarded as a data error. Range markets naming two
levels are refused outright.

**No SciPy.** One free parameter, so a log-spaced sweep plus golden-section
refinement — dependency-free and deterministic.

**One bug caught in the act.** The first threshold parser returned *one
trillion* for `$1,000 by December 31` — it read the `b` of "by" as a billions
suffix. Fixed with a lookahead, and there is a test named after it.

### Wiring

`services/analysis.py::calibrate_volatilities` blends the implied figure into
the realised one, weighted by the fit's own quality, and mutates
`estimate.volatilities` in place — risk, simulation and allocation all read
those same arrays, and a calibration only some of them saw would be worse than
none. `historical_volatilities` is preserved alongside so a recommendation can
say what moved and why. Assets with no market keep their realised estimate,
which is also what happens when a provider is unreachable.

## 1.3 Kalshi integration

**Verified live before writing any code.** Three details contradict the
published documentation, and one would have failed silently.

| Verified | Reality |
|---|---|
| Base URL | `https://external-api.kalshi.com/trade-api/v2` — not `trading-api` or `api.elections`, which most guides still name |
| Auth | None required for market data |
| Prices | `yes_bid_dollars: "0.9400"` — **decimal strings in dollars**, not integer cents. Sizes carry an `_fp` suffix. |
| Status | `"active"`, not `"open"` — `?status=open` returns an empty array |
| Series lookup | `/markets?series_ticker=X` returns nothing once that series' events expire; go via `/events?series_ticker=X&status=open` first |

**The integer-cents assumption is the dangerous one.** Coding to the documented
shape would have made every probability a hundredth of its true value, and
nothing would have raised.

**What Kalshi gives that Polymarket does not.** A dense strike ladder. One live
BTC event, `KXBTCD-26SEP1817`, carries ~46 strikes from $64,500 to $89,000 in
$500 steps, each with a two-sided quote — against Polymarket's seven scattered
thresholds. The bid/ask spread is also a free quality signal Polymarket never
provided.

BTC fits at **40.2% annualised** from 21 usable strikes, rmse 0.022.

**Design: one curve, many exchanges.** Kalshi markets are returned as
`PredictionMarket`, the same model the Polymarket client produces, so
`quant/implied.py` consumes both without knowing which exchange priced a point.
`merge_sources` concatenates per asset **before** fitting — every quote is a
point on the same curve, so one fit over the union is simpler and better
informed than reconciling two finished signals. Each point keeps its `source`,
so a fit reports who contributed.

**Horizon handling — option C.** A fitted sigma is annualised by construction,
so a five-day ladder does yield a usable annual figure; that is what makes this
work on day one. But annualising assumes a flat term structure, and crypto's is
not. So a horizon-matched expiry wins over a deeper mismatched one, and a
mismatched fit is marked and discounted:

```
horizon   5d   sigma=40.2%   matched=True    weight=0.50
horizon  30d   sigma=40.2%   matched=False   weight=0.25
horizon  90d   sigma=40.2%   matched=False   weight=0.25
```

**A mistake made and corrected mid-build.** The first version folded the
horizon penalty into `quality`, which made the 90-day fallback come out at
weight **0.00** — a rejection dressed up as a fallback, which is not option C.
Quality now measures only how well the curve was fitted; `horizon_matched` is a
separate axis applied as a 0.5 multiplier in `weight_for`. A poor fit is still
worth nothing at any horizon, so the penalty cannot resurrect one. A test
asserts the fallback weight is strictly between zero and the matched weight.

**Quality filters**, each tested against the recorded ladder: spread wider than
0.10 refused, open interest below 100 refused, crossed books refused, `between`
strikes skipped, status must be `active`. The recorded ladder loses 2 of 23
strikes — the deep out-of-the-money ones quoting 0.00/0.03 with no volume.

**Fixtures are recorded, not invented.** `tests/fixtures/kalshi_btc_ladder.py`
holds the live response verbatim, with a header explaining why. An invented
fixture would have encoded the documentation's wrong shape.

**Series are curated, not discovered.** The category scan returns 115 crypto
series that are mostly FDV bets, airdrop odds and 15-minute scalps; the list is
paginated; and `KXBTCD` — the most useful series found — was not on the first
page.

## 1.4 The 300-second probability window

`fetch_probability_change(window_seconds=300)` came straight from
`reference.ipynb`, where it returned `+0.00%` on nearly every market. A
300-second window at minute fidelity has no ticks on a book holding a few
hundred dollars — first and last price were the same tick.

Now 24 hours at hourly fidelity, with a $1,000 liquidity floor. Thin markets
are not queried at all: `None` reads as "no signal", which is true, where `0.0`
would read as "no movement", which the data cannot support. Field renamed
`change_5m` -> `probability_change_24h` (it was unused by the frontend).

## 1.5 Documentation and correctness

`backend/README.md` described a project that no longer existed. Its opening
block claimed the goal layer, analysis agents, allocation engine, judgement
agent, persistence and *every AWS service* were unimplemented, and that "no
endpoint produces a recommendation" — all of it built. Test count said 89
against a real 268. Fourteen live routes were missing from the endpoint table.
All corrected, plus a new *Market-implied volatility* section and an honest
rewrite of the "volatility is historical" limitation.

`docs/backend/context.md` — frozen and marked superseded. It stopped
mid-sentence in section 10; sections 10-16 were never written, yet the code
they would have described is finished. Sections 1-9 are kept because the code
still cites them. Original text untouched below the new header.

`backend/.env.example` — region corrected to `eu-north-1` (the live `.env`, the
SQS URL and the RDS host already agreed; the example file was the outlier),
`CHAT_MODEL` default aligned with `config.py`, and a note added spelling out
that `AWS_ENABLED=true` locally turns on the 5-minute refresh job and makes the
dev machine an SQS consumer.

`backend/pyproject.toml` — real description, both authors.

## 1.6 Housekeeping

- **ESLint** — flat `eslint.config.mjs` extending `next/core-web-vitals`,
  `lint` and `lint:fix` scripts, dev dependencies added. `next lint` is removed
  in Next 15.
- **`distDir`** — production builds go to `.next-build`, dev keeps `.next`.
  `next build` while `next dev` is running previously overwrote the chunks the
  dev server held open, failing as `Cannot find module './586.js'`.
- **`scan_truncated` regression test** — the flag existed and was asserted, but
  nothing checked it *reaches a user*. The new test asserts it becomes an
  "Incomplete scan" finding. A low page cap once hid a $19.5M WBTC position.

## 1.7 Previous session (2026-09-12)

`backend/validation.ipynb` — an assertion-driven replacement for
`reference.ipynb`, which proved the endpoints responded but not that they
returned usable data. Fixes: native ETH decoded (all four chains had printed
`Unknown`, silently dropping 6,774 ETH), `withPrices` actually read, spam
filtered before any ratio maths, stable-vs-volatile classification exercised,
24-hour change, and `wallet_assets` built from the wallet instead of referenced
undefined.

---

# Part 2 — What needs to be done

Ordered by what unblocks the most.

## 2.1 Yours — cannot be done for you

| # | Task | Why it is yours |
|---|---|---|
| 1 | **Request SES production access** (`eu-north-1`) | AWS console. Gates all email work, 1-2 day turnaround, can bounce back for more detail. File it first. |
| 2 | **Request the CloudFront origin timeout increase** (60s -> 180s) | AWS quota request. Long free-text recommendations 504 without it. |
| 3 | **Create IAM user `wallerina-deploy`**, `aws configure`, delete root access keys, enable root MFA | AWS console. The CLI is currently root. |
| 4 | **Rotate the Alchemy key and strip it from git history** | Credential handling. The literal key is in `reference.ipynb` cell 2 and in history — a new key alone leaves the old one retrievable from any clone. Use `git filter-repo` or BFG. |
| 5 | **Click through Draft Swaps with a real wallet** | Needs a wallet. Cover: no rebalance required; a sale entirely inside the gas reserve; an unsupported network (`opt-mainnet`); a token with null decimals; one symbol held across several networks. |
| 6 | **`npm install` in `frontend/`** | Pulls the ESLint packages added this session. |
| 7 | **One `/api/chat` call** to confirm `nvidia/nemotron-3-super-120b-a12b` handles forced function calls | Structured output depends on forcing a single function call. The README originally chose Kimi K2.6 for tool-calling strength; confirm nemotron was deliberate. |

## 2.2 Next things I can pick up

**Verify the rest of the Kalshi series map.** Only `KXBTCD` is confirmed to
have open events with a live ladder. ETH, SOL, XRP and the others came from the
series listing, not individual checks — and `KXETHMAXM` turned out to be
expired when checked. One pass of `/events?series_ticker=X&status=open` per
ticker. **Right now the map is partly guesswork sitting in committed code.**

**Wire `KXUSDTMIN` into the stablecoin analyst.** That agent runs on no
external data at all, and this is a live market pricing exactly the de-peg risk
it exists to assess. Deliberately kept out of `ASSET_SERIES` — it prices a
de-peg, not a price level, and must never enter a price distribution.

**Kalshi refresh job** — cache ladders to S3 on the existing 5-minute schedule,
in the shared handler rather than one of the two schedulers.

**CloudWatch metrics** for Kalshi fetch failures and staleness.

**Beta-to-ETH fallback** for assets with no prediction market. Most holdings
will never have one.

**Generalise the session subject** — `issue_session(address)` /
`read_session -> address` hardcodes a wallet. Making it a typed principal
(`wallet:0x…` / `user:<id>`) is the load-bearing first step of email auth and
can be done before SES clears.

## 2.3 Blocked on section 2.1

- **Deploy (todo section 7)** — needs the IAM user. Not being run unattended:
  it creates billable infrastructure and is not cleanly reversible.
- **Email auth (section 4)** — needs SES out of the sandbox.
- **Draft-ready emails (section 5)** — needs email auth.

---

# Part 3 — What is pending, and honestly why

## 3.1 One thing left half-done this session

**`frontend/.gitignore` was not committed.** `next.config.mjs` now writes
production builds to `.next-build`, but that directory is not ignored — so the
next `next build` will offer the whole build output to git. The file was
prepared and delivered into the conversation but left out of the commit batch.

Fix is one line added to `frontend/.gitignore`:

```
.next-build
```

## 3.2 Deliberately left open

These are open because doing them badly is worse than leaving them.

**`MAX_STRESS_SHIFT`, still 0.10.** With a real distribution behind the signal
the cap deserves re-deriving — but re-deriving it honestly needs a backtest,
not another judgement call. Replacing one guess with a better-argued guess is
not progress.

**The allocation constants** — `REFERENCE_VOLATILITY = 0.55`,
`VOLATILITY_SENSITIVITY = 0.45`, the three `MAX_*_SHIFT` caps, the thresholds.
Reasoned defaults, never fitted against historical outcomes; the README says so
plainly.

**And this session put a question mark next to one of them.** The market is
pricing ETH near 100% and BTC near 40%. A single 55% "reference volatility"
standing for the whole risk environment is doing work it probably should not.
Not changed, because changing it on one afternoon's observation would repeat
exactly the mistake the constant already represents.

## 3.3 Known limits of what was built

Written into the module docstrings rather than glossed:

- **A lognormal fitted to market quantiles is still a lognormal.** This does not
  make the model fat-tailed. Real crypto returns are more extreme, so tail
  estimates remain, if anything, optimistic.
- **These are risk-neutral probabilities**, carrying risk premia and fees — not
  real-world probabilities.
- **Prediction-market coverage is thin.** Only majors have usable ladders;
  everything else falls back to the historical estimate until beta-to-ETH lands.
- **`production_problems()` reads ambient environment variables**, not just
  `.env`. Discovered while testing: a container with `AWS_ACCESS_KEY_ID` set in
  its environment trips the static-keys guard even with a clean `.env`. Worth
  remembering on ECS.

## 3.4 Compliance, not yet read

**Kalshi's API terms** — data use and display rules. The client calls only
public market-data endpoints and never touches orders or portfolio, and shows
no trading links, but the terms have not been read. Do this before anything
ships publicly.

---

# Appendix — files changed this session

All committed to the working tree.

```
backend/src/backend/quant/implied.py              new    the implied CDF and fit
backend/src/backend/services/kalshi/__init__.py   new
backend/src/backend/services/kalshi/client.py     new    Kalshi ladder client
backend/tests/test_implied.py                     new    43 tests
backend/tests/test_kalshi.py                      new    23 tests
backend/tests/fixtures/__init__.py                new
backend/tests/fixtures/kalshi_btc_ladder.py       new    recorded live response
backend/validation.ipynb                          new    (previous session)

backend/src/backend/services/execution.py         $5-leg boundary
backend/src/backend/services/analysis.py          calibration + both exchanges
backend/src/backend/services/polymarket/client.py thresholds, expiry, 24h window
backend/src/backend/models/market.py              threshold, end_date, source
backend/src/backend/core/config.py                Kalshi settings
backend/tests/test_services.py                    scan_truncated surfacing
backend/README.md                                 status, routes, new section
backend/pyproject.toml                            description, authors
backend/.env.example                              region, model, AWS warning
docs/backend/context.md                           frozen, marked superseded
frontend/eslint.config.mjs                        new
frontend/next.config.mjs                          distDir
frontend/package.json                             eslint scripts and deps
todo.md                                           rewritten, items ticked

frontend/.gitignore                               PREPARED, NOT COMMITTED
```
