"use client";

import Button from "@/components/Button";
import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import { Notice } from "@/components/States";
import { useWallet } from "@/components/WalletProvider";
import Donut from "@/components/charts/Donut";
import FanChart from "@/components/charts/FanChart";
import { ratio, usd } from "@/lib/format";
import styles from "../page.module.css";
import PerformancePanel from "./PerformancePanel";

export default function DashboardPage() {
  const { address, portfolio, risk, simulation, marketStress, excluded } = useWallet();

  const header = (
    <PageHeader
      eyebrow="Overview"
      title="Dashboard"
      description="Live holdings for the connected wallet, the risk measured from their price history, and the range of outcomes the simulator produces."
      actions={
        <Button href="/simulations" variant="primary">
          Run a simulation
        </Button>
      }
    />
  );

  return (
    <PageState header={header}>
      {() => {
        const allocation = portfolio.holdings.slice(0, 8).map((holding) => ({
          id: `${holding.network}:${holding.contract_address ?? "native"}`,
          symbol: holding.symbol,
          weight: holding.portfolio_ratio * 100,
        }));

        return (
          <>
            {portfolio.scan_truncated && (
              <Notice>
                This wallet holds more tokens than were scanned, so totals may be
                understated. It is heavily airdropped; only priced, non-spam
                positions are counted.
              </Notice>
            )}

            <div className={`${styles.statRow} ${styles.statRow4}`}>
              <Stat
                label="Portfolio value"
                value={usd(portfolio.total_value_usd, { decimals: 0 })}
                note={`${portfolio.holdings_kept} positions across ${portfolio.chains.length} networks`}
                size="lg"
                emphasis
              />
              <Stat
                label="Stablecoin allocation"
                value={ratio(portfolio.stablecoin_ratio)}
                note={usd(portfolio.stablecoin_value_usd, { decimals: 0 })}
                size="lg"
              />
              <Stat
                label="Annualised volatility"
                value={ratio(risk.portfolio_annual_volatility)}
                note={`From ${risk.observations} days of history`}
                size="lg"
              />
              <Stat
                label="Value at Risk"
                value={ratio(risk.value_at_risk)}
                note={`${usd(risk.value_at_risk_usd, { compact: true })} · ${ratio(risk.confidence, { decimals: 0 })} / 1 day`}
                size="lg"
              />
            </div>

            <PerformancePanel address={address} />

            <div className={`${styles.grid} ${styles.splitWide}`}>
              <Panel
                title="Simulated outcomes"
                meta={`${simulation.simulations.toLocaleString("en-US")} paths · ${simulation.horizon_days} days · median with 25–75 and 5–95 bands`}
              >
                <FanChart
                  paths={simulation.fan.map((band) => ({
                    t: String(band.day),
                    p5: band.p5,
                    p25: band.p25,
                    median: band.median,
                    p75: band.p75,
                    p95: band.p95,
                  }))}
                  formatValue={(value) => usd(value, { compact: true })}
                />
                <p className={styles.helper}>
                  The simulator assumes zero expected return, so this is a picture
                  of risk rather than a forecast. The spread, not the centre line,
                  is the information.
                </p>
              </Panel>

              <Panel title="Allocation" meta="By share of total value">
                <div className={styles.stack}>
                  <Donut
                    segments={allocation}
                    caption={ratio(portfolio.volatile_ratio, { decimals: 0 })}
                    captionLabel="Volatile"
                  />
                  <Meter
                    label="Stablecoins"
                    value={portfolio.stablecoin_ratio * 100}
                    display={ratio(portfolio.stablecoin_ratio)}
                  />
                  <Meter
                    label="Volatile and unknown"
                    value={portfolio.volatile_ratio * 100}
                    display={ratio(portfolio.volatile_ratio)}
                    muted
                  />
                </div>
              </Panel>
            </div>

            <div className={`${styles.grid} ${styles.split}`}>
              <Panel
                title="Where the risk sits"
                meta="Share of total portfolio volatility"
              >
                <div className={styles.stack}>
                  {risk.assets.slice(0, 6).map((asset) => (
                    <Meter
                      key={asset.symbol}
                      label={`${asset.symbol} · ${ratio(asset.weight)} of book`}
                      value={Math.max(asset.risk_contribution * 100, 0)}
                      display={ratio(asset.risk_contribution)}
                    />
                  ))}
                  <p className={styles.helper}>
                    Risk contribution is not the same as weight. A small position
                    in a volatile asset can carry far more risk than its size
                    suggests.
                  </p>
                </div>
              </Panel>

              <Panel title="Outlook" meta={`${simulation.horizon_days}-day horizon`}>
                <div className={styles.stack}>
                  <dl className={styles.defs}>
                    <div className={`${styles.def} ${styles.defStrong}`}>
                      <dt>95th percentile</dt>
                      <dd>{usd(simulation.p95, { decimals: 0 })}</dd>
                    </div>
                    <div className={styles.def}>
                      <dt>Median</dt>
                      <dd>{usd(simulation.median_value, { decimals: 0 })}</dd>
                    </div>
                    <div className={`${styles.def} ${styles.defStrong}`}>
                      <dt>5th percentile</dt>
                      <dd>{usd(simulation.p5, { decimals: 0 })}</dd>
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
                      <dt>Market stress signal</dt>
                      <dd>
                        {marketStress?.available
                          ? `${ratio(marketStress.score)} · ×${marketStress.volatility_multiplier.toFixed(2)} volatility`
                          : "Unavailable"}
                      </dd>
                    </div>
                  </dl>

                  {!marketStress?.available && (
                    <p className={styles.helper}>
                      Prediction-market data could not be reached, so no
                      volatility adjustment was applied. Polymarket is blocked on
                      some networks.
                    </p>
                  )}
                </div>
              </Panel>
            </div>

            {excluded.length > 0 && (
              <Notice>
                Excluded from the risk model for lack of usable price history:{" "}
                {excluded.join(", ")}. They are still counted in the portfolio
                total.
              </Notice>
            )}
          </>
        );
      }}
    </PageState>
  );
}
