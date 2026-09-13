# Wallerina: Context

What has been done so far, and the decisions behind it. Last updated 2026-09-13.

## What Wallerina is

A portfolio **advice** app for crypto wallets. It reads a wallet's public balances,
measures risk, simulates possible futures and recommends a rebalance toward a goal.

**It never trades.** It holds no private keys and never signs or sends
transactions, for the user or for any wallet holder. Analysing any public address
is invisible to that wallet's owner.

## Stack

| Layer | What |
|---|---|
| Frontend | Next.js 15.5 (App Router), React 19, CSS modules |
| Backend | FastAPI (Python 3.12, `uv`), LangGraph agent pipeline |
| Models | NVIDIA NIM (OpenAI-compatible), default `moonshotai/kimi-k2.6`. Bedrock was dropped because the AWS account blocks inference. No Claude/Anthropic API. |
| Market data | Alchemy (balances, prices, history), Polymarket (market stress), 0x (swap quotes) |
| AWS (`eu-north-1`) | Aurora PostgreSQL (IAM auth), S3, SQS, CloudWatch, Secrets Manager, ECS Fargate, Lambda, EventBridge, CloudFront |

## Features built

### Backend
- **Portfolio:** wallet scan across networks, spam filtering, asset classification (`/api/portfolio`).
- **Risk:** volatility, Value at Risk, risk contribution per asset, correlations (`/api/risk`).
- **Monte Carlo simulation:** fan charts and scenarios. Heavy runs are queued on SQS (`/api/simulate`, `/api/simulate/jobs`).
- **Market stress:** a Polymarket-derived signal that scales simulated volatility (`/api/market-stress`, `/api/prediction-markets`).
- **Agent pipeline:** goal parsing → analyst agents → allocation engine → judgement → grounding (`/api/recommendation`).
- **Goals:** presets, or free text read by the goal agent. Saving a goal requires wallet sign-in.
- **History:** backfilled and recorded performance and risk over time (`/api/history/*`).
- **Chat:** streaming assistant with tools (`/api/chat`).
- **Wallet sign-in:** EIP-4361 / SIWE (`/api/auth/nonce`, `/api/auth/verify`).
- **Draft swaps:** `/api/execution/{address}/plan` turns a recommendation into same-network swaps.
  - Read-only, **no sign-in**, so it works for any wallet.
  - Quote and transaction endpoints still require the wallet owner's sign-in, and are not used by the UI.
- **Production hardening:** per-client rate limiting, CORS checks, startup safety checks in production.
- **Background refresh:** market data, prediction data and wallet snapshots every 5 minutes.

### Frontend pages
Dashboard, Portfolio, Risk, Simulations, Recommendations, plus Chat.
- **Dashboard:** stats, performance, simulated outcomes, allocation, risk contribution, outlook, and the **Draft swaps** panel.
- **Draft swaps panel:** loads on demand and is clearly labelled "Drafts only · Wallerina never signs, sends or executes anything".

## Work done in this session

1. **Dev server crash** (`Cannot find module './586.js'`). A `next build` had overwritten the `.next` folder used by `next dev`. Fix: stop the dev server, delete `.next`, restart. Never build while dev is running.
2. **Duplicate React key in `LineChart`.** A short series gave repeated x-tick indexes, which are now deduplicated.
3. **Audit:**
   - 267 backend tests pass. One fails: `test_execution` expects no swap at exactly a $5 leg after the $25 gas reserve, while the code allows it. Undecided.
   - The frontend has no ESLint config (`next lint` is deprecated).
4. **`backend/.env`:**
   - Added `SESSION_SECRET` (generated) and the user added `ZEROEX_API_KEY`.
   - Removed the empty `AWS_SESSION_TOKEN`, `AWS_PROFILE`, `AWS_ENDPOINT_URL` and `AWS_SECRET_ID`.
   - A backup was made in the session scratchpad.
5. **Trading safety confirmed:**
   - No key custody or transaction sending anywhere.
   - Drafts require no action from, and are invisible to, the wallet owner.
6. **Draft swaps panel** added to the dashboard, and the plan endpoint made public (read-only).
7. **Deploy preparation:**
   - `deploy/wallerina.yaml`:
     - Added CloudFront in front of the ALB for HTTPS without a domain.
     - The ALB security group accepts traffic only from the CloudFront origin-facing prefix list.
     - `ApiUrl` output is now `https://<id>.cloudfront.net`.
   - `deploy/deploy.sh` looks up the prefix list and passes it to the stack.
   - Rate limiter uses `CloudFront-Viewer-Address` when `BEHIND_CLOUDFRONT=true`, so each visitor gets their own limit. A test was added.
   - The template passes `aws cloudformation validate-template`, and the Docker image excludes `.env`.
   - `deploy/README.md` updated.

## Deploy decisions (not yet deployed)

| Topic | Decision |
|---|---|
| AWS identity | Create IAM user `wallerina-deploy` (AdministratorAccess). The CLI is currently root, so delete root keys and enable MFA. |
| Frontend hosting | Vercel |
| API HTTPS | CloudFront (no custom domain) |
| Alerts | SNS email to the owner's Gmail |

**Deploy order:**
1. IAM user and `aws configure`.
2. `npx vercel --prod` to get the frontend URL.
3. `CORS_ORIGINS=<vercel url> ALARM_EMAIL=… ./deploy/deploy.sh`.
4. Put API keys in the `wallerina/app` secret.
5. Force a new ECS deployment.
6. Set `NEXT_PUBLIC_API_URL` on Vercel and redeploy.
7. Confirm the SNS email.
8. Check `/health/database`.

**Known limits:**
- CloudFront waits at most 60 seconds for the origin (a quota increase allows up to 180), so long free-text recommendations may return 504.
- Expected cost is about $50–60/month plus Aurora, which rarely pauses because of the 5-minute snapshot job.
