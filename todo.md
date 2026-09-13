# Wallerina: TODO

Last reviewed 2026-09-13 against the working tree (backend source, tests, docs,
frontend, `deploy/`).

**Suite: 312/312 passing** as of 2026-09-13.

**Ground rules**
- **Advice only.** Never sign, send or execute trades for anyone.
- **Integrations are passive for the UI.** New data sources, such as Kalshi, add no
  new pages, panels or controls. They make the numbers and explanations the
  existing sections already show more accurate.
- **The engine decides, the model explains.** Specification section 2. Any new
  signal enters through `quant/`, never through a prompt.

---

## 0. Do these first — they have waiting time attached

These are requests to third parties. Everything downstream of them is blocked
until they clear, so filing them late costs days that no amount of coding back.

- [ ] **Request Amazon SES production access** (`eu-north-1`). The sandbox only
      sends to verified addresses, which makes sections 4 and 5 untestable end
      to end. Review typically takes 24–48 hours and can bounce back for more
      detail, so file it before writing any email code.
  - [ ] Verify the sending domain (or a single sender address as a stopgap)
  - [ ] Write the use-case description: transactional only, user-initiated
        sign-in codes plus opt-in rebalance alerts, one-click unsubscribe
- [ ] **Request the CloudFront origin response timeout increase** (60s default →
      up to 180s). Long free-text recommendations return 504 without it. Quota
      increases are not instant.
- [x] **Settle the AWS region.** Done 2026-09-13 — `eu-north-1` everywhere.
      `.env.example` shipped `ap-south-1`; the live `.env`, the SQS URL and the
      RDS host were already `eu-north-1`, so the example file was the wrong one
      and has been corrected.
- [ ] **Create IAM user `wallerina-deploy`**, `aws configure`, delete the root
      access keys, enable root MFA. The CLI is currently running as root.

---

## 1. Drafts section in the UI — mostly done (2026-09-13)

- [x] "Draft swaps" panel on the dashboard
      (`frontend/src/app/(app)/dashboard/DraftSwapsPanel.js`)
- [x] Plan endpoint readable without wallet sign-in (read-only)
      (`POST /api/execution/{address}/plan`, `main.py:551`)
- [x] Clear "drafts only, nothing is executed" labelling
- [ ] **Click through with a real wallet.** Cover, deliberately:
  - a wallet with no rebalance required (the panel should say so, not sit empty)
  - a wallet whose sale is entirely inside the gas reserve, so `skipped` is
    populated and `legs` is empty
  - a wallet holding an unsupported network (`opt-mainnet`) so the
    "execution is not supported on this network" note renders
  - a wallet with a token whose `decimals` is null, so that note renders
  - a wallet where a symbol is held on several networks, confirming the pooled
    sale is not double-counted
- [x] **Decide the $5-leg edge case.** Done 2026-09-13 — see 1.1. 268/268 pass.

### 1.1 The $5-leg decision — resolved 2026-09-13

Was the one failing test in the suite. The boundary is now **exclusive**: a leg
must be worth strictly more than `MIN_LEG_USD`. Four lines changed in
`services/execution.py` — the constant's comment, and all three comparisons, so
the rule reads the same in every place it is applied:

```
MIN_LEG_USD = 5.0
if remaining   <= MIN_LEG_USD: break        # was <
if amount_usd  <= MIN_LEG_USD: continue     # was <   <- the fix
if remaining    > MIN_LEG_USD:              # was >=  (the "no executable
                                            #          position" note)
```

The suite is 268/268. The reasoning below is kept as the record of why.

**Where it is.** `backend/src/backend/services/execution.py`, in `build_legs`:

```python
MIN_LEG_USD = 5.0                                   # "a swap smaller than this
                                                    #  costs more in gas and
                                                    #  slippage than it moves"

reserve = GAS_RESERVE_USD.get(network, 0.0) ...     # eth-mainnet: 25.0
amount_usd = min(remaining, holding.value_usd - reserve)
if amount_usd < MIN_LEG_USD:
    continue
```

**The failing case.** `tests/test_execution.py::test_unsupported_networks_unknown_decimals_and_leftovers_are_reported`
holds $30 of native ETH on mainnet and asks to sell all of it.
`30 − 25 = 5.0`, and `5.0 < 5.0` is `False`, so the code builds a $5 leg. The
test asserts `legs == []` with the comment *"the $30 of ETH is inside the $25
mainnet gas reserve plus the $5 minimum"*.

**Recommendation: change the code, not the test.** The constant's own docstring
says a swap below this size costs more than it moves — at exactly $5 on
Ethereum mainnet, gas alone exceeds the trade. The boundary should be
exclusive.

- [ ] Change `if amount_usd < MIN_LEG_USD` to `if amount_usd <= MIN_LEG_USD`
- [ ] Sweep the other two comparisons in the same function so the rule reads the
      same everywhere: `if remaining < MIN_LEG_USD: break` and the trailing
      `if remaining >= MIN_LEG_USD:` that emits the "no executable position"
      note. Decide once whether $5 exactly is executable, then apply it three
      times.
- [ ] Confirm the test's other two assertions still hold — with the leg
      suppressed, `remaining` stays at $30 and the
      "of the ETH sale has no executable position" note must still fire.
- [ ] Add a comment naming the boundary, so the next reader does not re-litigate
      it.

---

## 2. Documentation drift — cheap, and currently misleading

`backend/README.md` describes a version of the project that no longer exists.
Anyone onboarding reads it first.

- [x] **Fix the "Implemented / Not implemented" block at the top.** Done
      2026-09-13. It had claimed
      claims the goal layer, analysis agents, allocation engine, judgement
      agent, LLM explanation, persistence and *every AWS service* are not
      implemented, and that "no endpoint produces a recommendation". All of it
      is built: `agents/goal.py`, `agents/analysts.py`, `quant/allocation.py`,
      `agents/judgement.py`, `aws/`, and `GET /api/recommendation/{address}`
      at `main.py:432`.
- [x] **Fix the test count.** Done — README said 89; the suite is 268.
- [x] **Complete the endpoint table.** Done — fourteen routes added:
      `/health/database`, `/api/simulate/jobs/{job_id}`, `/api/goals/presets`,
      `GET` and `PUT /api/goal/{address}`, `/api/refresh/run`,
      `/api/history/{address}/performance`, `/api/history/{address}/risk`,
      `/api/auth/nonce`, `/api/auth/verify`, and all four `/api/execution/*`
      routes.
- [x] **Decide what `docs/backend/context.md` is now.** Done 2026-09-13 —
      frozen and marked superseded, with a header pointing to the root
      `context.md`, the backend README and this file. Sections 1–9 stay as the
      record of intent, since the code still cites them; 10–16 are not being
      written. Original text unchanged below the header.
      <details><summary>original item</summary> The original spec still
      ends mid-sentence inside section 10 ("The market data layer provides
      historical and current information."), with sections 10–16 never written —
      yet the code those sections would have described is finished. Either
      finish it as the record of intent, or mark it superseded by the root
      `context.md` and keep it as a frozen design document. Leaving a truncated
      spec as the canonical reference is the worst of the three.</details>
- [x] **`CHAT_MODEL` default.** Resolved 2026-09-13 — the code is right, the
      docs were stale. `config.py` defaults to
      `nvidia/nemotron-3-super-120b-a12b`; README and `.env.example` said
      `moonshotai/kimi-k2.6` and have been corrected.
      **Still open:** confirm nemotron was deliberate. The README chose Kimi for
      tool-calling strength, and structured output depends on *forcing* a single
      function call — exercise `/api/chat` once and check it holds.
- [x] **`backend/pyproject.toml`:** Done — real description, both authors.
- [ ] **Rotate the Alchemy key committed in `reference.ipynb`.** The literal key
      is in cell 2 and in git history. A new key alone is not enough — strip it
      from history with `git filter-repo` or BFG, or the old one stays
      retrievable from any clone.

---

## 3. Make the prediction-market signal mean something

This sits **before** Kalshi deliberately. Kalshi's value is better probability
coverage, but there is nowhere good to put those probabilities yet — the
current signal throws away the information it already has. Build the
representation first, then Kalshi plugs into it.

**The problem, from the code.** `services/polymarket/client.py::compute_market_stress`
takes the liquidity-weighted mean probability of every market classified
`downside`, and maps it to a volatility multiplier in `[1.0, 1.5]`. The
*threshold* of each market is discarded. So "Will ETH dip to $800" (2.25%) and
"Will ETH dip to $1,500" (14%) are averaged as if they said the same thing. The
README already calls this "an intentionally simple stand-in".

**What the data actually is.** Each downside market is `P(price ≤ X)` and each
upside market is `P(price ≥ X)`, so `1 − p` is also a point on the same curve.
A family of them at one expiry is a market-implied cumulative distribution.
Verified against live values pulled in `reference.ipynb`, ETH at 31 Dec 2026:

| Threshold | P(X ≤ t) | Source side |
|---|---|---|
| $800 | 2.25% | dip |
| $1,000 | 6.50% | dip |
| $1,500 | 14.00% | dip |
| $6,000 | 95.70% | reach |
| $7,500 | 97.15% | reach |
| $8,000 | 97.85% | reach |
| $10,000 | 98.55% | reach |

Seven points, monotonic, zero violations, backed by $2.6M of volume on the
deepest market. `backend/validation.ipynb` parses and validates this already.

- [x] **Parse the threshold out of each market question.** Done —
      `implied.parse_threshold`, 15/15 real questions. `_direction()` in
      `polymarket/client.py` already classifies upside/downside with a regex;
      extend it to return the dollar level too. Handle `$150k` and `$0.05`
      alike. `validation.ipynb` has a parser tested against 11 real questions,
      including two that correctly return nothing.
- [x] **Group by expiry before doing anything else.** Done —
      `points_from_markets` keys on expiry; a test asserts they never mix. Dec 2026 and Sep 2026 are
      different random variables. Mixing them yields a curve that looks fine and
      means nothing.
- [x] **Build and validate the CDF.** Done — isotonic repair with a
      violation count, and a 25% ceiling above which the curve is refused. Require ≥3 points at one expiry; check
      monotonicity and reject or repair curves that violate it (stale quotes on
      thin books are the usual cause).
- [x] **Feed it to the simulator.** Done — a lognormal fitted to the market's
      own quantiles; `calibrate_volatilities` blends it into
      `estimate.volatilities`. ETH fits at ~100% against a 55% reference. `quant/monte_carlo.py` currently takes one
      scalar `volatility_multiplier` and a zero-drift lognormal. Replace that,
      for assets with a usable curve, with a distribution fitted to reproduce
      the market's tail probabilities. Keep zero drift — this changes the
      *shape*, not the direction.
  - [x] Validation: simulated `P(terminal ≤ X)` must land within a stated
        tolerance of the market's `P` at each observed threshold. That is a real
        assertion, unlike "the simulation is stable".
- [x] **Keep the scalar multiplier as the fallback** — done; `compute_market_stress`
      is untouched and still applies. for assets with no curve,
      so nothing regresses when coverage is thin.
- [ ] **Coverage fallback for everything else.** Still open. Most holdings will never have a
      prediction market — beta-to-ETH is the obvious default. Record which path
      each asset took so the explanation can say so.
- [x] **Fix the 5-minute probability window.** Done — 24h at hourly fidelity,
      a $1,000 liquidity floor, and the field renamed
      `change_5m` → `probability_change_24h` (unused by the frontend).
      `fetch_probability_change(token_id, window_seconds=300)` carried straight
      over from `reference.ipynb`, where it returned `+0.00%` on nearly every
      market: a 300-second window at `fidelity=1` has no ticks on a book with a
      few hundred dollars of liquidity. Widen to 24h (`fidelity=60`) or 7d, or
      restrict the call to markets above a liquidity floor.
- [ ] **Then revisit the allocation driver.** Still open, and deliberately:
      re-deriving `MAX_STRESS_SHIFT` honestly needs a backtest, not another
      judgement call. Left at 0.10. `MAX_STRESS_SHIFT = 0.10` in
      `quant/allocation.py` is a bounded nudge on a signal that currently
      carries little information. With a real distribution behind it, the cap
      deserves re-deriving rather than re-guessing.

---

## 4. Email-based auth

Wallet sign-in (SIWE) only works for wallets you own. Email auth lets anyone keep
an account, watch any address, and receive notifications.

- [ ] **Method:** passwordless magic link or 6-digit one-time code (no passwords
      to store)
- [ ] **Sending:** Amazon SES — see section 0, the access request gates this
- [ ] **Generalise the session subject first.** This is the load-bearing change
      and it is small. `services/auth.py` has `issue_session(address)` and
      `read_session(token) -> str | None` returning an address; every
      authenticated route treats the subject as a wallet. Make the subject a
      typed principal (`wallet:0x…` / `user:<id>`) before adding a second
      identity kind, or the distinction leaks into every handler.
- [ ] **Data (Aurora).** `aws/database.py::migrate()` creates schema on boot, so
      these are additive `CREATE TABLE IF NOT EXISTS` blocks alongside the
      existing `wallets`, `portfolio_snapshots`, `risk_metrics`, `simulations`,
      `recommendations`, `wallet_goals`, `auth_nonces`, `executions`:
  - `users` (email, created_at, verified_at)
  - `login_codes` (hashed code, expiry, attempts)
  - `watched_wallets` (user_id, address, goal, notify)
- [ ] **Sessions:** reuse the existing signed-session mechanism
      (`SESSION_SECRET`), with the subject as the user id instead of a wallet
- [ ] **Security:**
  - rate limit code requests per email and per IP — `core/ratelimit.py` already
    exists and is wired for per-client limits; reuse it rather than adding a
    second mechanism
  - expire codes after about 10 minutes
  - limit attempts
  - make "email sent" responses identical whether or not the account exists
  - store only a hash of the code, never the code
- [ ] **Keep SIWE:** a user may link wallets they own. Watching a public address
      needs no proof of ownership.
- [ ] **UI:** only the minimum — a sign-in screen and a "watch this wallet"
      toggle. This is the one unavoidable UI addition.
- [ ] **Deploy:**
  - SES permissions on the task and Lambda roles
  - sender address in config
  - CORS already covers the Vercel origin
- [ ] **Tests:** code issue and verify, expiry, reuse, brute-force limits,
      enumeration resistance

---

## 5. Email the user when a new draft is ready

- [ ] **When:** the background snapshot job builds drafts for every watched
      wallet. Two schedulers exist for the same three jobs —
      `services/refresh.py` in-process and `aws/handlers.py` on EventBridge,
      with `REFRESH_ENABLED` deciding which. Add the draft step to the shared
      handler, not to one of the two paths, or it will run twice in one
      environment and never in the other.
- [ ] **Notify only on change:**
  - store a fingerprint of the last draft (the legs rounded to about $10) per
    watched wallet
  - email only when it changes **and** `rebalance_required` is true
  - the fingerprint needs its own table or a column on `watched_wallets`
- [ ] **Throttle:** at most one email per wallet per day, with a digest when
      several wallets change
- [ ] **Email content:**
  - wallet (shortened address)
  - goal
  - current vs target stablecoin share
  - drafted swaps (sell → buy, $ value, reason)
  - link to the dashboard
  - the line "Wallerina never executes trades"
- [ ] **Unsubscribe:** one-click link (signed token — the `SESSION_SECRET` MAC
      in `services/auth.py` already does exactly this shape of thing), plus a
      per-wallet notify setting
- [ ] **Delivery:**
  - SES templates
  - bounce and complaint handling via SNS, which disables notifications for that
    email
- [ ] **Cost guard:** drafts run the full recommendation pipeline, which calls a
      model. Cap watched wallets per user, skip unchanged portfolios, and put a
      ceiling on model calls per refresh cycle — a hundred watched wallets every
      five minutes is 28,800 pipeline runs a day.
- [ ] **Tests:** fingerprint change detection, throttling, unsubscribe, the
      double-scheduler case

---

## 6. Integrate the Kalshi API for better probability estimates

Kalshi is a CFTC-regulated prediction market (event contracts priced $0–$1, which
reads as an implied probability). It complements Polymarket, which is already
integrated and blocked on some networks.

**Sequencing note:** section 3 builds the representation these probabilities
belong in. Doing Kalshi first means blending two sources into a signal that
discards thresholds — twice the plumbing for the same weak number.

### 6.1 Integration work (backend only)
- [ ] **Client** `services/kalshi/client.py`, alongside `services/polymarket/`
  - Use the public market-data endpoints of Trade API v2 (series, events,
    markets, order book, trades, candlesticks). Read-only data needs no account.
  - Never use the order or portfolio endpoints (advice only).
  - Reuse `services/http.py` (timeouts, retries) and the S3 cache used for
    Polymarket.
  - Mirror the Polymarket client's circuit breaker — it already has one, and a
    second source with no breaker becomes the new single point of failure.
- [ ] **Refresh job:** cache the relevant Kalshi markets in S3 on the existing
      5-minute schedule
- [ ] **Market selection:** a curated map of series to what they inform (crypto
      price levels, Fed, CPI, recession and so on). Verify current tickers
      against the live API before hard-coding.
- [ ] **Data quality:**
  - ignore illiquid markets (thin order book, wide spread, low volume or open
    interest)
  - weight by liquidity
  - discard stale prices
- [ ] **Blending:** combine Kalshi and Polymarket into one probability estimate
  - blend at the CDF level from section 3, not at the scalar level
  - use either source alone when only one is reachable
  - record which sources contributed
- [ ] **Config:** `KALSHI_ENABLED`, base URL, and an optional API key only if a
      rate-limit tier needs it (stored in Secrets Manager)
- [ ] **Tests:** recorded fixtures, liquidity filtering, blending,
      source-down fallbacks
- [ ] **Compliance note:** read Kalshi's API terms for data use and display. Show
      no trading links.

### 6.2 What Kalshi can give Wallerina, by existing section
All of these feed existing numbers and text. **No new UI.**

#### Dashboard
- **Market stress signal (Outlook):** blend Kalshi macro and crypto markets into
  the existing stress score and volatility multiplier, so it keeps working when
  Polymarket is blocked
- **Simulated outcomes:** the fan chart's volatility scaling uses the blended
  multiplier
- **Draft swaps:** the reason text can cite the probability that drove a
  de-risking move

#### Simulations
- **Implied price distribution:** Kalshi BTC/ETH price-range and above/below
  markets give market-implied probabilities at fixed dates — the same shape as
  section 3, from a second source
- **Event-conditioned scenarios:** existing scenario runs get probabilities
  attached (for example "Fed hike" or "recession") instead of being unweighted
  what-ifs
- **Probability-weighted expected outcome:** weight scenario results by
  market-implied event odds

#### Risk
- **Forward-looking volatility:** combine historical volatility with
  market-implied uncertainty. The README lists "volatility is historical" as a
  known limitation; this is the fix for it.
- **Tail risk / VaR adjustment:** raise VaR when markets price a high chance of
  large moves or macro shocks
- **Regime flag:** macro markets (rate path, CPI surprise, recession odds) set a
  calm / normal / stressed regime that the risk model already understands
  through the multiplier
- **Probability history:** store daily snapshots so the existing risk-history
  charts can reflect regime changes over time

#### Recommendations (agent pipeline)
- **Analyst context:** give the macro and market analyst agents a compact, cited
  probability summary (for example "Kalshi: 68% chance of a rate cut at the next
  FOMC"). The analysts in `agents/analysts.py` are deterministic — keep them
  that way; this is data, not a prompt.
- **Judgement:** tighten or loosen the target stablecoin share when stress
  probabilities cross thresholds, as a new bounded `AllocationDriver` in
  `quant/allocation.py`. A test already asserts the drivers sum to the decision;
  any new driver must keep that true.
- **Grounding:** every probability quoted in the explanation carries its source,
  market and timestamp, so `agents/grounding.py` can verify it
- **Confidence:** when Kalshi and Polymarket disagree strongly, lower the stated
  confidence and say so. `_confidence()` in `allocation.py` already docks 0.08
  when stress data is missing — disagreement belongs in the same function.

#### Chat
- **Existing assistant:** a read-only tool such as `get_event_probabilities(topic)`
  in `services/chat.py` lets it answer "what are the odds BTC is above $X by
  Friday?" with sourced numbers, with no UI change

#### Background / data
- **Candlestick history:** backtest whether probability moves preceded drawdowns
  and tune the stress weights offline
- **Source health:** CloudWatch metrics for Kalshi fetch failures and staleness,
  added to existing alarms

### 6.3 Out of scope
- Placing orders, portfolio or balance endpoints, or any trading links
  (advice only)
- New Kalshi-specific pages, panels, tickers or charts (passive UI rule)

---

## 7. Deployment (carried over, in progress)

Prerequisites in section 0 — IAM user, region decision — come first.

- [ ] Commit current changes, so image tags are not `-dirty`
- [ ] `npx vercel --prod` to get the frontend URL
- [ ] `CORS_ORIGINS=<vercel url> ALARM_EMAIL=… ./deploy/deploy.sh`
- [ ] Put `ALCHEMY_API_KEY`, `NVIDIA_API_KEY`, `ZEROEX_API_KEY` (and later SES /
      Kalshi config) in the `wallerina/app` secret, then force a new ECS
      deployment
- [ ] Set `NEXT_PUBLIC_API_URL` on Vercel and redeploy
- [ ] Confirm the SNS email, check `/health/database`
- [ ] Verify `APP_ENV=production` actually refuses to start on wildcard CORS and
      static AWS keys — the guard exists; confirm it fires before trusting it
- [ ] Confirm `BEHIND_CLOUDFRONT=true` is set, or every visitor shares one rate
      limit behind the CloudFront origin
- [ ] Watch the first Aurora bill. The 5-minute snapshot job means the cluster
      rarely pauses; expected cost is about $50–60/month plus Aurora.

---

## 8. Housekeeping

- [x] ESLint set up — flat `eslint.config.mjs` extending
      `next/core-web-vitals`, `lint`/`lint:fix` scripts, dev dependencies added.
      **Run `npm install` once** to pull eslint, eslint-config-next and
      @eslint/eslintrc.
- [x] Production builds use `.next-build`; dev keeps `.next`. `.gitignore`
      updated to cover both.
- [ ] Backtest the allocation constants. `REFERENCE_VOLATILITY = 0.55`,
      `VOLATILITY_SENSITIVITY = 0.45`, the three `MAX_*_SHIFT` caps and the
      thresholds in `quant/allocation.py` are reasoned defaults that have never
      been fitted against historical outcomes — the README says so plainly. At
      minimum, record what each number is meant to achieve so a future change
      can be argued about rather than guessed.
- [x] Regression test added for the `scan_truncated` path —
      `test_truncation_reaches_the_analyst_as_a_finding` asserts the flag
      becomes an "Incomplete scan" finding, not just a boolean nobody reads.
      (Old note:) A low page cap once
      hid a $19.5M WBTC position; the cap is now 20 pages and the flag exists,
      but nothing asserts the flag is surfaced to the caller.

---

## Suggested order

```
0. SES request  ─┐
   CF quota      ├─ file now, they wait in the background
   region fix    │
   IAM user     ─┘
        │
        ├─→ 1. $5-leg fix + wallet click-through   (hours, unblocks a green suite)
        ├─→ 2. doc drift + key rotation            (hours, stops misleading readers)
        │
        ├─→ 7. deploy                              (needs IAM + region)
        │         │
        │         └─→ 4. email auth  ─→  5. draft emails   (need SES + a live API)
        │
        └─→ 3. implied CDF from Polymarket         (the real signal work)
                  │
                  └─→ 6. Kalshi                    (plugs into 3)
```

Sections 1 and 2 are a morning's work and clear the deck. Section 3 is the one
that changes what the product actually knows.
