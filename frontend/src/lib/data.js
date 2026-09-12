/* ---------------------------------------------------------------------------
   Mock data layer.

   The backend (FastAPI) is not wired up yet, so every page reads from here.
   Values are produced by a seeded generator, which keeps server and client
   renders byte-identical. When the API lands, replace the exports below with
   fetches of the same shape and the components will not need to change.
   --------------------------------------------------------------------------- */

function seeded(seed) {
  let state = seed;
  return function next() {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

/* Gaussian via Box-Muller, driven by the seeded uniform stream. */
function gaussian(rand) {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function walk({ seed, length, start, drift, volatility, floor = 0 }) {
  const rand = seeded(seed);
  const series = [];
  let value = start;
  for (let i = 0; i < length; i += 1) {
    value = Math.max(floor, value * (1 + drift + volatility * gaussian(rand)));
    series.push(value);
  }
  return series;
}

/* Rescales a generated series so it terminates on a known value — keeps the
   chart's last point consistent with the headline figure beside it. */
function endingAt(values, target) {
  const factor = target / values[values.length - 1];
  return values.map((value) => value * factor);
}

function daysAgo(n) {
  const date = new Date(Date.UTC(2026, 8, 12));
  date.setUTCDate(date.getUTCDate() - n);
  return date.toISOString();
}

function toSeries(values, step = 1) {
  return values.map((value, index) => ({
    t: daysAgo((values.length - 1 - index) * step),
    v: value,
  }));
}

/* --- Wallet ------------------------------------------------------------- */

export const wallet = {
  address: "0x7A31F4c2Be09D5a8E6b1C4fD25a09E7b3C41Df82",
  label: "Primary wallet",
  provider: "MetaMask",
  connectedAt: daysAgo(41),
  networks: [
    { id: "ethereum", name: "Ethereum", enabled: true, assets: 5 },
    { id: "arbitrum", name: "Arbitrum", enabled: true, assets: 3 },
    { id: "base", name: "Base", enabled: true, assets: 2 },
    { id: "polygon", name: "Polygon", enabled: false, assets: 0 },
    { id: "optimism", name: "Optimism", enabled: false, assets: 0 },
  ],
};

/* --- Portfolio ---------------------------------------------------------- */

export const assets = [
  {
    symbol: "ETH",
    name: "Ethereum",
    chain: "Ethereum",
    class: "volatile",
    quantity: 19.4,
    price: 3184.22,
    value: 61773.87,
    change24h: 1.82,
    change30d: -6.41,
    volatility: 58.2,
    riskContribution: 41.3,
    beta: 1.14,
  },
  {
    symbol: "BTC",
    name: "Bitcoin",
    chain: "Ethereum",
    class: "volatile",
    quantity: 0.812,
    price: 58210.4,
    value: 47266.84,
    change24h: 0.94,
    change30d: -3.18,
    volatility: 46.7,
    riskContribution: 28.6,
    beta: 1.0,
  },
  {
    symbol: "SOL",
    name: "Solana",
    chain: "Base",
    class: "volatile",
    quantity: 184.6,
    price: 141.08,
    value: 26043.37,
    change24h: -2.47,
    change30d: -11.92,
    volatility: 78.4,
    riskContribution: 19.8,
    beta: 1.46,
  },
  {
    symbol: "ARB",
    name: "Arbitrum",
    chain: "Arbitrum",
    class: "volatile",
    quantity: 9420,
    price: 0.7431,
    value: 6999.0,
    change24h: -3.86,
    change30d: -18.34,
    volatility: 92.1,
    riskContribution: 7.4,
    beta: 1.71,
  },
  {
    symbol: "USDC",
    name: "USD Coin",
    chain: "Ethereum",
    class: "stablecoin",
    quantity: 28400,
    price: 1.0,
    value: 28400.0,
    change24h: 0.01,
    change30d: 0.0,
    volatility: 0.4,
    riskContribution: 1.8,
    beta: 0.01,
  },
  {
    symbol: "USDT",
    name: "Tether",
    chain: "Arbitrum",
    class: "stablecoin",
    quantity: 11250,
    price: 0.9998,
    value: 11247.75,
    change24h: -0.02,
    change30d: -0.01,
    volatility: 0.6,
    riskContribution: 0.9,
    beta: 0.01,
  },
  {
    symbol: "DAI",
    name: "Dai",
    chain: "Base",
    class: "stablecoin",
    quantity: 4300,
    price: 1.0002,
    value: 4300.86,
    change24h: 0.0,
    change30d: 0.02,
    volatility: 0.5,
    riskContribution: 0.2,
    beta: 0.01,
  },
];

const totalValue = assets.reduce((sum, asset) => sum + asset.value, 0);
const stableValue = assets
  .filter((asset) => asset.class === "stablecoin")
  .reduce((sum, asset) => sum + asset.value, 0);

export const portfolio = {
  totalValue,
  costBasis: 168400,
  totalReturn: totalValue - 168400,
  totalReturnPct: ((totalValue - 168400) / 168400) * 100,
  change24h: 0.42,
  change30d: -5.81,
  stablecoinValue: stableValue,
  stablecoinRatio: (stableValue / totalValue) * 100,
  volatileRatio: (1 - stableValue / totalValue) * 100,
  allocation: assets
    .map((asset) => ({
      symbol: asset.symbol,
      weight: (asset.value / totalValue) * 100,
      value: asset.value,
      class: asset.class,
    }))
    .sort((a, b) => b.weight - a.weight),
  chains: ["Ethereum", "Arbitrum", "Base"].map((chain) => {
    const value = assets
      .filter((asset) => asset.chain === chain)
      .reduce((sum, asset) => sum + asset.value, 0);
    return { chain, value, weight: (value / totalValue) * 100 };
  }),
  performance: toSeries(
    endingAt(
      walk({ seed: 17, length: 120, start: 168400, drift: 0.0002, volatility: 0.014 }),
      totalValue
    )
  ),
};

export const priceHistory = Object.fromEntries(
  assets.map((asset, index) => [
    asset.symbol,
    toSeries(
      walk({
        seed: 101 + index * 37,
        length: 90,
        start: asset.price * (asset.class === "stablecoin" ? 1 : 1.08),
        drift: asset.class === "stablecoin" ? 0 : -0.0006,
        volatility: asset.class === "stablecoin" ? 0.0004 : asset.volatility / 4200,
      })
    ),
  ])
);

export const transactions = [
  { id: "tx-01", type: "Sell", asset: "SOL", quantity: 42.5, value: 6021.4, chain: "Base", date: daysAgo(2) },
  { id: "tx-02", type: "Buy", asset: "USDC", quantity: 6000, value: 6000.0, chain: "Ethereum", date: daysAgo(2) },
  { id: "tx-03", type: "Buy", asset: "ETH", quantity: 2.1, value: 6742.9, chain: "Ethereum", date: daysAgo(9) },
  { id: "tx-04", type: "Sell", asset: "ARB", quantity: 3100, value: 2503.1, chain: "Arbitrum", date: daysAgo(16) },
  { id: "tx-05", type: "Buy", asset: "BTC", quantity: 0.14, value: 8109.2, chain: "Ethereum", date: daysAgo(23) },
  { id: "tx-06", type: "Transfer", asset: "DAI", quantity: 4300, value: 4300.0, chain: "Base", date: daysAgo(31) },
  { id: "tx-07", type: "Buy", asset: "USDT", quantity: 11250, value: 11250.0, chain: "Arbitrum", date: daysAgo(38) },
];

/* --- Risk ---------------------------------------------------------------- */

export const risk = {
  score: 68,
  band: "Elevated",
  previousScore: 61,
  volatility: 41.6,
  valueAtRisk: 12.4,
  valueAtRiskUsd: totalValue * 0.124,
  expectedShortfall: 18.9,
  expectedShortfallUsd: totalValue * 0.189,
  maxDrawdown: 27.3,
  concentration: 0.31,
  downsideExposure: 63.2,
  sharpe: 0.74,
  history: toSeries(
    walk({ seed: 53, length: 90, start: 54, drift: 0.0022, volatility: 0.035, floor: 5 })
  ),
  factors: [
    { name: "Market volatility", weight: 31, level: "High", note: "30d realised vol above 12m median" },
    { name: "Asset concentration", weight: 24, level: "Elevated", note: "Top two positions hold 58% of book" },
    { name: "Correlation clustering", weight: 18, level: "Elevated", note: "Volatile sleeve moves near-together" },
    { name: "Liquidity depth", weight: 14, level: "Moderate", note: "ARB depth thin at size" },
    { name: "Stablecoin exposure", weight: 8, level: "Low", note: "Peg deviation within tolerance" },
    { name: "Prediction markets", weight: 5, level: "Moderate", note: "Drawdown odds drifting upward" },
  ],
  indicators: [
    { name: "Realised volatility 30d", value: "41.6%", delta: 6.2 },
    { name: "Implied volatility", value: "48.1%", delta: 4.4 },
    { name: "Funding rate", value: "0.011%", delta: -0.9 },
    { name: "Stablecoin dominance", value: "8.9%", delta: 1.1 },
    { name: "Liquidity index", value: "0.62", delta: -0.07 },
    { name: "Drawdown probability 90d", value: "34%", delta: 5.0 },
  ],
  correlationAssets: ["ETH", "BTC", "SOL", "ARB", "USDC"],
  correlationMatrix: [
    [1.0, 0.86, 0.79, 0.72, -0.04],
    [0.86, 1.0, 0.74, 0.63, -0.02],
    [0.79, 0.74, 1.0, 0.81, -0.05],
    [0.72, 0.63, 0.81, 1.0, -0.03],
    [-0.04, -0.02, -0.05, -0.03, 1.0],
  ],
};

/* --- Market -------------------------------------------------------------- */

export const market = {
  sentiment: 38,
  sentimentLabel: "Cautious",
  regime: "Risk-off",
  signals: [
    { name: "30d realised volatility", reading: "41.6%", stance: "Negative" },
    { name: "Prediction market drawdown odds", reading: "34%", stance: "Negative" },
    { name: "Stablecoin peg stability", reading: "Stable", stance: "Neutral" },
    { name: "Spot liquidity", reading: "Thinning", stance: "Negative" },
    { name: "Trend strength", reading: "Weak", stance: "Neutral" },
  ],
};

/* --- Simulations --------------------------------------------------------- */

export const simulation = {
  defaults: { horizonDays: 90, runs: 10000, stablecoinRatio: 26 },
  expectedValue: 149820,
  medianValue: 146310,
  bestCase: 232400,
  worstCase: 71240,
  p5: 96840,
  p95: 208960,
  probabilityOfLoss: 38.4,
  expectedDrawdown: 19.7,
  fan: buildFan(),
  distribution: buildDistribution(),
  scenarios: [
    { name: "Current allocation", stablecoin: 26, expected: 149820, p5: 96840, drawdown: 19.7, lossProb: 38.4 },
    { name: "Recommended", stablecoin: 43, expected: 147150, p5: 118430, drawdown: 12.1, lossProb: 29.6 },
    { name: "Defensive", stablecoin: 60, expected: 144020, p5: 129870, drawdown: 7.4, lossProb: 21.8 },
    { name: "Aggressive", stablecoin: 10, expected: 152640, p5: 78210, drawdown: 28.9, lossProb: 46.2 },
  ],
};

function buildFan() {
  const steps = 90;
  const start = totalValue;
  const points = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const spread = Math.sqrt(t) * start * 0.46;
    const median = start * (1 + 0.0004 * i);
    points.push({
      t: daysAgo(-i),
      p5: median - spread * 0.92,
      p25: median - spread * 0.38,
      median,
      p75: median + spread * 0.4,
      p95: median + spread * 1.02,
    });
  }
  return points;
}

function buildDistribution() {
  const rand = seeded(991);
  const bins = new Array(28).fill(0);
  const min = 60000;
  const max = 250000;
  for (let i = 0; i < 20000; i += 1) {
    const draw = 150000 * Math.exp(0.32 * gaussian(rand) - 0.05);
    const index = Math.floor(((draw - min) / (max - min)) * bins.length);
    if (index >= 0 && index < bins.length) bins[index] += 1;
  }
  return bins.map((count, index) => ({
    from: min + ((max - min) / bins.length) * index,
    to: min + ((max - min) / bins.length) * (index + 1),
    count,
  }));
}

/* --- Recommendation ------------------------------------------------------ */

export const recommendation = {
  id: "rec-2026-09-12",
  generatedAt: daysAgo(0),
  targetStablecoinRatio: 43,
  acceptableRange: [38, 48],
  currentStablecoinRatio: portfolio.stablecoinRatio,
  confidence: 81,
  action: "Rebalance",
  expectedRiskAfter: 47,
  expectedReturnAfter: 8.4,
  expectedDrawdownAfter: 12.1,
  reasoning: [
    "Realised volatility across the volatile sleeve sits 6.2 points above its twelve-month median, and implied volatility is pricing further expansion rather than mean reversion.",
    "The volatile positions are behaving as a single exposure: pairwise correlation between ETH, BTC and SOL has risen above 0.74, so the book carries far less diversification than its position count suggests.",
    "Monte Carlo over 10,000 paths puts a 38.4% probability of loss on the current allocation at a 90-day horizon. Lifting stablecoins to 43% cuts that to 29.6% and halves expected drawdown, at a cost of 1.8% in expected terminal value.",
    "Stablecoin conditions are not a constraint: all three held pegs are inside tolerance and redemption depth is adequate for the proposed size.",
  ],
  trades: [
    { action: "Sell", asset: "SOL", quantity: 96.4, value: 13600, note: "Highest volatility contributor" },
    { action: "Sell", asset: "ARB", quantity: 5100, value: 3790, note: "Thin liquidity, weakest trend" },
    { action: "Sell", asset: "ETH", quantity: 3.4, value: 10826, note: "Trim to target weight" },
    { action: "Buy", asset: "USDC", quantity: 21200, value: 21200, note: "Primary stablecoin leg" },
    { action: "Buy", asset: "DAI", quantity: 7016, value: 7016, note: "Diversify peg issuer" },
  ],
  holds: ["BTC", "USDT"],
  evidence: [
    { label: "Paths simulated", value: "10,000" },
    { label: "Horizon", value: "90 days" },
    { label: "Loss probability now", value: "38.4%" },
    { label: "Loss probability after", value: "29.6%" },
    { label: "Expected drawdown now", value: "19.7%" },
    { label: "Expected drawdown after", value: "12.1%" },
  ],
};

export const analyses = [
  { id: "an-04", title: "Volatility regime shift detected", stance: "Reduce exposure", date: daysAgo(0) },
  { id: "an-03", title: "Correlation clustering across volatile sleeve", stance: "Monitor", date: daysAgo(3) },
  { id: "an-02", title: "Stablecoin peg review", stance: "No action", date: daysAgo(8) },
  { id: "an-01", title: "Quarterly allocation review", stance: "Rebalance", date: daysAgo(21) },
];

/* --- Settings ------------------------------------------------------------ */

export const preferences = {
  riskObjective: "Balanced",
  riskObjectives: ["Capital preservation", "Balanced", "Growth"],
  horizon: "6 months",
  horizons: ["1 month", "3 months", "6 months", "1 year", "3 years"],
  maxDrawdown: 20,
  stablecoins: [
    { symbol: "USDC", enabled: true },
    { symbol: "USDT", enabled: true },
    { symbol: "DAI", enabled: true },
    { symbol: "PYUSD", enabled: false },
  ],
  analysis: [
    { key: "auto-analysis", name: "Automatic daily analysis", description: "Re-run the risk engine every 24 hours", enabled: true },
    { key: "prediction-markets", name: "Prediction market signals", description: "Include external probability feeds in the risk model", enabled: true },
    { key: "deep-sim", name: "Extended Monte Carlo", description: "Raise default path count from 10,000 to 50,000", enabled: false },
  ],
  notifications: [
    { key: "rebalance", name: "Rebalance recommended", description: "When target allocation leaves the acceptable range", enabled: true },
    { key: "risk-spike", name: "Risk score spike", description: "When the score rises more than 10 points in a day", enabled: true },
    { key: "peg", name: "Stablecoin peg deviation", description: "When a held stablecoin drifts beyond tolerance", enabled: true },
    { key: "digest", name: "Weekly digest", description: "Summary of portfolio and market conditions", enabled: false },
  ],
};
