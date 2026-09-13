# Wallerina: TODO

**Ground rules**
- **Advice only.** Never sign, send or execute trades for anyone.
- **Integrations are passive for the UI.** New data sources, such as Kalshi, add no
  new pages, panels or controls. They make the numbers and explanations the
  existing sections already show more accurate.

---

## 1. Drafts section in the UI ✅ Done (2026-09-13)
- [x] "Draft swaps" panel on the dashboard (`dashboard/DraftSwapsPanel.js`)
- [x] Plan endpoint readable without wallet sign-in (read-only)
- [x] Clear "drafts only, nothing is executed" labelling
- [ ] Click through with a real wallet, including states with no swaps and with skipped notes
- [ ] Decide the $5-leg edge case and fix `test_execution` accordingly

## 2. Email-based auth
Wallet sign-in (SIWE) only works for wallets you own. Email auth lets anyone keep
an account, watch any address, and receive notifications.

- [ ] **Method:** passwordless magic link or 6-digit one-time code (no passwords to store)
- [ ] **Sending:** Amazon SES in `eu-north-1`
  - verify the sending domain or address
  - request production access (leave the sandbox)
- [ ] **Data (Aurora):**
  - `users` (email, created_at, verified_at)
  - `login_codes` (hashed code, expiry, attempts)
  - `watched_wallets` (user_id, address, goal, notify)
- [ ] **Sessions:** reuse the existing signed-session mechanism (`SESSION_SECRET`), with the subject as the user id instead of a wallet
- [ ] **Security:**
  - rate limit code requests per email and per IP
  - expire codes after about 10 minutes
  - limit attempts
  - make "email sent" responses the same whether or not the account exists
- [ ] **Keep SIWE:** a user may link wallets they own. Watching a public address needs no proof of ownership.
- [ ] **UI:** only the minimum, a sign-in screen and a "watch this wallet" toggle. This is the one unavoidable UI addition.
- [ ] **Deploy:**
  - SES permissions on the task and Lambda roles
  - sender address in config
  - CORS already covers the Vercel origin
- [ ] **Tests:** code issue and verify, expiry, reuse, brute-force limits

## 3. Email the user when a new draft is ready
- [ ] **When:** the background snapshot job (EventBridge → Lambda, every 5 minutes) builds drafts for every watched wallet
- [ ] **Notify only on change:**
  - store a fingerprint of the last draft (the legs rounded to about $10) per watched wallet
  - email only when it changes and a rebalance is required
- [ ] **Throttle:** at most one email per wallet per day, with a digest when several wallets change
- [ ] **Email content:**
  - wallet (shortened address)
  - goal
  - current vs target stablecoin share
  - drafted swaps (sell → buy, $ value, reason)
  - link to the dashboard
  - the line "Wallerina never executes trades"
- [ ] **Unsubscribe:** one-click link (signed token), plus a per-wallet notify setting
- [ ] **Delivery:**
  - SES templates
  - bounce and complaint handling via SNS, which disables notifications for that email
- [ ] **Cost guard:** drafts run the recommendation pipeline, so cap watched wallets per user and skip unchanged portfolios
- [ ] **Tests:** fingerprint change detection, throttling, unsubscribe

## 4. Integrate the Kalshi API for better probability estimates
Kalshi is a CFTC-regulated prediction market (event contracts priced $0–$1, which
reads as an implied probability). It complements Polymarket, which is already
integrated and blocked on some networks.

### 4.1 Integration work (backend only)
- [ ] **Client** `services/kalshi/client.py`, alongside `services/polymarket/`
  - Use the public market-data endpoints of Trade API v2 (series, events, markets, order book, trades, candlesticks). Read-only data needs no account.
  - Never use the order or portfolio endpoints (advice only).
  - Reuse `services/http.py` (timeouts, retries) and the S3 cache used for Polymarket.
- [ ] **Refresh job:** cache the relevant Kalshi markets in S3 on the existing 5-minute schedule
- [ ] **Market selection:** a curated map of series to what they inform (crypto price levels, Fed, CPI, recession and so on). Verify current tickers against the live API before hard-coding.
- [ ] **Data quality:**
  - ignore illiquid markets (thin order book, wide spread, low volume or open interest)
  - weight by liquidity
  - discard stale prices
- [ ] **Blending:** combine Kalshi and Polymarket into one stress / probability estimate
  - use either source alone when only one is reachable
  - record which sources contributed
- [ ] **Config:** `KALSHI_ENABLED`, base URL, and an optional API key only if a rate-limit tier needs it (stored in Secrets Manager)
- [ ] **Tests:** recorded fixtures, liquidity filtering, blending, source-down fallbacks
- [ ] **Compliance note:** read Kalshi's API terms for data use and display. Show no trading links.

### 4.2 What Kalshi can give Wallerina, by existing section
All of these feed existing numbers and text. **No new UI.**

#### Dashboard
- **Market stress signal (Outlook):** blend Kalshi macro and crypto markets into the existing stress score and volatility multiplier, so it keeps working when Polymarket is blocked
- **Simulated outcomes:** the fan chart's volatility scaling uses the blended multiplier
- **Draft swaps:** the reason text can cite the probability that drove a de-risking move

#### Simulations
- **Implied price distribution:** Kalshi BTC/ETH price-range and above/below markets give market-implied probabilities at fixed dates
  - use them to calibrate Monte Carlo tails, replacing the zero-drift normal with a spread that matches the market
  - check simulated P(price above X) against Kalshi's P
- **Event-conditioned scenarios:** existing scenario runs get probabilities attached (for example "Fed hike" or "recession") instead of being unweighted what-ifs
- **Probability-weighted expected outcome:** weight scenario results by market-implied event odds

#### Risk
- **Forward-looking volatility:** combine historical volatility with market-implied uncertainty (how wide Kalshi's price-range distribution is)
- **Tail risk / VaR adjustment:** raise VaR when markets price a high chance of large moves or macro shocks
- **Regime flag:** macro markets (rate path, CPI surprise, recession odds) set a calm / normal / stressed regime that the risk model already understands through the multiplier
- **Probability history:** store daily snapshots so the existing risk-history charts can reflect regime changes over time

#### Recommendations (agent pipeline)
- **Analyst context:** give the macro and market analyst agents a compact, cited probability summary (for example "Kalshi: 68% chance of a rate cut at the next FOMC")
- **Judgement:** tighten or loosen the target stablecoin share when stress probabilities cross thresholds (a small, explainable adjustment)
- **Grounding:** every probability quoted in the explanation carries its source, market and timestamp, so the grounding step can verify it
- **Confidence:** when Kalshi and Polymarket disagree strongly, lower the stated confidence and say so in the text

#### Chat
- **Existing assistant:** a read-only tool such as `get_event_probabilities(topic)` lets it answer "what are the odds BTC is above $X by Friday?" with sourced numbers, with no UI change

#### Background / data
- **Candlestick history:** backtest whether probability moves preceded drawdowns and tune the stress weights offline
- **Source health:** CloudWatch metrics for Kalshi fetch failures and staleness, added to existing alarms

### 4.3 Out of scope
- Placing orders, portfolio or balance endpoints, or any trading links (advice only)
- New Kalshi-specific pages, panels, tickers or charts (passive UI rule)

---

## 5. Deployment (carried over, in progress)
- [ ] Create IAM user `wallerina-deploy`, run `aws configure`, delete root access keys, enable root MFA
- [ ] Commit current changes, so image tags are not `-dirty`
- [ ] `npx vercel --prod` to get the frontend URL
- [ ] `CORS_ORIGINS=<vercel url> ALARM_EMAIL=… ./deploy/deploy.sh`
- [ ] Put `ALCHEMY_API_KEY`, `NVIDIA_API_KEY` (and later SES/Kalshi config) in the `wallerina/app` secret, then force a new ECS deployment
- [ ] Set `NEXT_PUBLIC_API_URL` on Vercel and redeploy
- [ ] Confirm the SNS email, check `/health/database`
- [ ] If long recommendations return 504, request a CloudFront origin response timeout increase

## 6. Housekeeping
- [ ] Set up ESLint for the frontend (`npx @next/codemod@canary next-lint-to-eslint-cli .`)
- [ ] Give production builds their own `distDir` so they never clobber `next dev`
