# Wallerina UI Design Specification

## Global Rules

### Typography

* Landing page: **Gideon Roman**
* All other pages: **Open Sans**
* No other font families

### Color Palette

Strictly use only these colors:

* **Pitch Black:** `#050505` — primary background
* **Deep Black:** `#0A0A0A` — secondary surfaces
* **Soft Black:** `#111111` — panels / table rows
* **Light Sepia:** `#E8E0D2` — primary accent
* **Very Light Sepia:** `#F2ECE2` — highlighted elements / important values
* **Sepia Grey:** `#BDB5A8` — secondary text
* **Dark Sepia:** `#8F887D` — muted text / borders

The sepia must be **extremely light, desaturated and close to off-white**.

The sepia should visually feel like **aged ivory / warm off-white**, not gold.

### Pigment accents (amended)

Charts and a small number of semantic labels may carry colour. Every accent is
held near the chroma floor and warm-shifted, so it reads as **dye soaked into
paper** rather than screen colour — pigment on aged stock, not a dashboard.

Fixed slot order, assigned in sequence, never cycled:

| Slot | Name | Hex |
|---|---|---|
| 1 | Verdigris | `#23A59F` |
| 2 | Madder | `#BA5745` |
| 3 | Woad | `#5388C2` |
| 4 | Ochre | `#B18F34` |
| 5 | Plum | `#985683` |
| 6 | Celadon | `#66A268` |
| 7 | Indigo | `#635FA3` |
| 8 | Sienna | `#BD7138` |

Correlation uses a diverging scale instead — two hues either side of a warm
neutral (`#302D29`), because the sign of a correlation matters as much as its
size and an opacity ramp renders `-0.8` and `+0.8` identically.

Reserved semantic marks: stablecoin = verdigris, volatile = sienna,
unknown = plum, loss = madder, gain = verdigris. These are never reused as a
series colour.

**Rules that still hold:**

* Colour appears on **data marks and classification labels only**. Grid lines,
  axes, tick labels, chrome, panels and type stay black and sepia.
* Still around **85–90% of the application is black or near-black**.
* No saturated, neon or pure screen colour. Nothing should read as gold.
* Identity is never carried by colour alone — a legend is always present, and
  classification always shows the word as well as the mark.
* Panels carry a **paper film**: one flat warm wash at ~2% over the surface, so
  pigment and black sit on a single ground.

The palette is validated as a categorical scale against the `#0A0A0A` panel
surface — lightness band, chroma floor, colour-vision-deficiency separation
(worst adjacent ΔE 12.4 under deuteranopia), normal-vision floor (21.5) and
≥3:1 contrast. Re-run the check before changing any value.

### UI Style

* Pitch-black dark theme
* Monochrome aesthetic
* Very light sepia accents
* Sharp rectangular geometry
* **No rounded corners**
* **No border-radius**
* No emojis
* No badges
* No pills
* No blinking dots
* No glassmorphism
* No excessive shadows
* No gradients
* No decorative noise
* No unnecessary illustrations
* No excessive animations
* No floating cards
* No crypto clichés

---

# Landing Page

## Hero

* Full-screen ballerina background image
* Minimal dark/black ballerina silhouette
* Very subtle image treatment
* `logo.png` from `Wallerina/frontend/assets/logo.png` positioned top-left
* Centered **"Wallerina"**
* Gideon Roman
* Bold typography
* Black text
* Large scale
* Minimal composition

### Tagline

**"Wallerina - Agents to make your wallet stable like a Ballerina"**

### Hero actions

* Connect Wallet
* Enter Dashboard

### Landing page background

Use the light sepia/off-white palette only on the landing page.

The landing page should feel like a **minimalist luxury editorial identity**, not a conventional SaaS landing page.

---

# 1. Dashboard

* Portfolio value
* Total return
* Asset allocation
* Risk score
* Stablecoin allocation
* Recommended stablecoin allocation
* Market sentiment
* Top risk factors
* Portfolio performance chart
* Asset allocation chart
* Recent analysis
* View recommendation button

---

# 2. Portfolio

* Total portfolio value
* Asset table
* Asset allocation
* Asset prices
* Asset quantities
* Asset performance
* Asset risk contribution
* Asset detail panel
* Historical price chart
* Transaction history
* Chain breakdown
* Stablecoin holdings

---

# 3. Risk

* Overall risk score
* Volatility
* Value at Risk
* Expected Shortfall
* Maximum drawdown
* Concentration risk
* Correlation matrix
* Risk contribution by asset
* Downside exposure
* Risk history chart
* Market-risk indicators
* Risk factor breakdown

---

# 4. Simulations

* Monte Carlo simulation chart
* Simulation controls
* Time horizon
* Number of simulations
* Current allocation
* Simulated portfolio distribution
* Expected portfolio value
* Median portfolio value
* Best-case outcome
* Worst-case outcome
* 5th percentile
* 95th percentile
* Probability of loss
* Expected drawdown
* Scenario comparison
* Run simulation button

---

# 5. Recommendations

* Recommended stablecoin allocation
* Current allocation
* Target allocation
* Allocation difference
* Recommended trades
* Assets to sell
* Assets to hold
* Stablecoins to buy
* Expected risk after rebalance
* Expected return after rebalance
* Expected drawdown after rebalance
* Recommendation reasoning
* Market signals
* Monte Carlo evidence
* Rebalancing preview
* Execute rebalance button

---

# 6. Settings

* Connected wallet
* Supported networks
* Wallet preferences
* Risk objective
* Investment horizon
* Maximum acceptable drawdown
* Stablecoin preferences
* Analysis preferences
* Notification settings
* Disconnect wallet

---

## Color Application Rule

For **all pages after Landing**:

```text
BACKGROUND
#050505

PANELS
#0A0A0A
#111111

PRIMARY TEXT
#F2ECE2

SECONDARY TEXT
#BDB5A8

BORDERS
#8F887D

IMPORTANT DATA
#E8E0D2
#F2ECE2

BUTTONS
#E8E0D2 background
#050505 text
```

Use sepia **sparingly**. Around **85–90% of the application should visually remain black/near-black**, with the very light sepia reserved for typography, charts, important numbers, controls and key actions.

The sepia should **never look yellow or gold**. It should look like **white with a very subtle warm sepia cast**.
