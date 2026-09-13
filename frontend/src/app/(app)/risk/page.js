"use client";

import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import { Notice } from "@/components/States";
import { useWallet } from "@/components/WalletProvider";
import Matrix from "@/components/charts/Matrix";
import { ratio, usd } from "@/lib/format";
import styles from "../page.module.css";
import RiskHistoryPanel from "./RiskHistoryPanel";

export default function RiskPage() {
  const { address, risk, portfolio, simulation, excluded } = useWallet();

  const header = (
    <PageHeader
      eyebrow="Analysis"
      title="Risk"
      description="What the wallet's own price history says about how much it can lose, and which holdings are responsible."
    />
  );

  return (
    <PageState header={header} loadingLabel="Measuring risk">
      {() => (
        <>
          <div className={`${styles.statRow} ${styles.statRow5}`}>
            <Stat
              label="Annualised volatility"
              value={ratio(risk.portfolio_annual_volatility)}
              note={`${risk.observations} days of history`}
              size="lg"
              emphasis
            />
            <Stat
              label="Value at Risk"
              value={ratio(risk.value_at_risk)}
              note={`${usd(risk.value_at_risk_usd, { compact: true })} · ${ratio(risk.confidence, { decimals: 0 })} / 1 day`}
              size="lg"
            />
            <Stat
              label="Expected shortfall"
              value={ratio(risk.expected_shortfall)}
              note={`${usd(risk.expected_shortfall_usd, { compact: true })} · mean of the tail`}
              size="lg"
            />
            <Stat
              label="Worst drawdown"
              value={ratio(risk.max_drawdown)}
              note="Largest peak-to-trough in the window"
              size="lg"
            />
            <Stat
              label="Downside exposure"
              value={ratio(risk.downside_exposure)}
              note="Share of book that can lose value"
              size="lg"
            />
          </div>

          <RiskHistoryPanel address={address} />

          <div className={`${styles.grid} ${styles.split}`}>
            <Panel
              title="Correlation matrix"
              meta={`Pairwise daily return correlation · ${risk.observations} observations`}
            >
              {risk.correlation_symbols.length < 2 ? (
                <p className={styles.helper}>
                  Only one asset has usable history, so there is no correlation to
                  measure.
                </p>
              ) : (
                <>
                  <Matrix
                    labels={risk.correlation_symbols}
                    matrix={risk.correlation_matrix}
                  />
                  <p className={styles.helper}>
                    Density encodes the absolute correlation. Assets that move
                    together provide far less diversification than their position
                    count suggests — this is the single most important input to
                    the simulation.
                  </p>
                </>
              )}
            </Panel>

            <Panel
              title="Risk contribution by asset"
              meta="Euler decomposition — contributions sum to 100%"
            >
              <div className={styles.stack}>
                {risk.assets.slice(0, 10).map((asset) => (
                  <div key={asset.symbol}>
                    <Meter
                      label={asset.symbol}
                      value={Math.max(asset.risk_contribution * 100, 0)}
                      display={ratio(asset.risk_contribution)}
                    />
                    <p className={styles.factorNote}>
                      {ratio(asset.weight)} of the book · {ratio(asset.annual_volatility)}{" "}
                      volatility · beta {asset.beta_to_portfolio.toFixed(2)}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className={`${styles.grid} ${styles.split}`}>
            <Panel title="Simulated downside" meta={`${simulation.horizon_days}-day Monte Carlo`}>
              <dl className={styles.defs}>
                <div className={`${styles.def} ${styles.defStrong}`}>
                  <dt>5th percentile outcome</dt>
                  <dd>{usd(simulation.p5, { decimals: 0 })}</dd>
                </div>
                <div className={styles.def}>
                  <dt>Worst simulated path</dt>
                  <dd>{usd(simulation.worst_case, { decimals: 0 })}</dd>
                </div>
                <div className={styles.def}>
                  <dt>Probability of loss</dt>
                  <dd>{ratio(simulation.probability_of_loss)}</dd>
                </div>
                <div className={styles.def}>
                  <dt>Expected drawdown</dt>
                  <dd>{ratio(simulation.expected_drawdown)}</dd>
                </div>
                <div className={styles.def}>
                  <dt>Drawdown exceeded by 5% of paths</dt>
                  <dd>{ratio(simulation.max_drawdown_p95)}</dd>
                </div>
              </dl>
            </Panel>

            <Panel title="Structure" meta="Composition of the risk">
              <div className={styles.stack}>
                <dl className={styles.defs}>
                  <div className={styles.def}>
                    <dt>Concentration (HHI)</dt>
                    <dd>{risk.concentration.toFixed(3)}</dd>
                  </div>
                  <div className={styles.def}>
                    <dt>Stablecoin allocation</dt>
                    <dd>{ratio(portfolio.stablecoin_ratio)}</dd>
                  </div>
                  <div className={styles.def}>
                    <dt>Assets in the risk model</dt>
                    <dd>{risk.assets.length}</dd>
                  </div>
                  <div className={styles.def}>
                    <dt>Observation window</dt>
                    <dd>{risk.observations} days</dd>
                  </div>
                </dl>
                <p className={styles.helper}>
                  Volatility is a single historical estimate per asset. There is no
                  GARCH, no implied volatility and no jump component, so real crypto
                  tails are heavier than this model shows.
                </p>
              </div>
            </Panel>
          </div>

          {excluded.length > 0 && (
            <Notice>
              Excluded for insufficient price history: {excluded.join(", ")}. Their
              value still counts toward the portfolio total but not toward these
              risk figures.
            </Notice>
          )}
        </>
      )}
    </PageState>
  );
}
