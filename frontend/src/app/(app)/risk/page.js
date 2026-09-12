import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import LineChart from "@/components/charts/LineChart";
import Matrix from "@/components/charts/Matrix";
import { assets, risk } from "@/lib/data";
import { percent, usd } from "@/lib/format";
import styles from "../page.module.css";

export const metadata = { title: "Risk · Wallerina" };

export default function RiskPage() {
  const volatileAssets = assets
    .filter((asset) => asset.class === "volatile")
    .sort((a, b) => b.riskContribution - a.riskContribution);

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="Risk"
        description="How much loss the current book can produce, where that loss comes from, and how the risk environment has moved."
      />

      <div className={`${styles.statRow} ${styles.statRow5}`}>
        <Stat
          label="Overall risk score"
          value={`${risk.score}`}
          delta={risk.score - risk.previousScore}
          deltaLabel={`${risk.score - risk.previousScore} vs last week`}
          note={risk.band}
          size="lg"
          emphasis
        />
        <Stat label="Volatility" value={percent(risk.volatility)} note="Annualised, 30d realised" size="lg" />
        <Stat
          label="Value at Risk"
          value={percent(risk.valueAtRisk)}
          note={`${usd(risk.valueAtRiskUsd, { compact: true })} · 95% / 1 day`}
          size="lg"
        />
        <Stat
          label="Expected shortfall"
          value={percent(risk.expectedShortfall)}
          note={`${usd(risk.expectedShortfallUsd, { compact: true })} · tail mean`}
          size="lg"
        />
        <Stat label="Maximum drawdown" value={percent(risk.maxDrawdown)} note="Trailing 12 months" size="lg" />
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel title="Risk history" meta="90 days · overall score">
          <LineChart
            series={risk.history}
            formatValue={(value) => value.toFixed(0)}
          />
        </Panel>

        <Panel title="Risk factor breakdown" meta="Weighted contribution to score">
          <div className={styles.stack}>
            {risk.factors.map((factor) => (
              <div key={factor.name}>
                <Meter
                  label={factor.name}
                  value={factor.weight}
                  display={`${factor.weight}% · ${factor.level}`}
                />
                <p className={styles.factorNote}>{factor.note}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.split}`}>
        <Panel title="Correlation matrix" meta="Pairwise 90 day return correlation">
          <Matrix labels={risk.correlationAssets} matrix={risk.correlationMatrix} />
          <p className={styles.helper}>
            Density encodes the absolute correlation. The volatile sleeve is
            clustering above 0.7, so position count overstates the actual
            diversification of the book.
          </p>
        </Panel>

        <Panel title="Risk contribution by asset" meta="Share of total portfolio risk">
          <div className={styles.stack}>
            {volatileAssets.map((asset) => (
              <Meter
                key={asset.symbol}
                label={`${asset.symbol} · ${percent(asset.volatility)} vol`}
                value={asset.riskContribution}
                display={percent(asset.riskContribution)}
              />
            ))}
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.split}`}>
        <Panel title="Market risk indicators" meta="External readings feeding the model" flush>
          <ul className={styles.indicators}>
            {risk.indicators.map((indicator) => (
              <li key={indicator.name} className={styles.indicator}>
                <span className={styles.indicatorName}>{indicator.name}</span>
                <span className={styles.indicatorValue}>{indicator.value}</span>
                <span className={styles.indicatorDelta}>
                  {indicator.delta > 0 ? "▲" : "▼"} {Math.abs(indicator.delta).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Downside exposure" meta="Capital sitting in loss-bearing assets">
          <div className={styles.stack}>
            <Stat
              label="Exposed capital"
              value={percent(risk.downsideExposure)}
              note="Share of book that can lose value in a drawdown"
              size="lg"
              emphasis
            />
            <dl className={styles.defs}>
              <div className={styles.def}>
                <dt>Concentration risk (HHI)</dt>
                <dd>{risk.concentration.toFixed(2)}</dd>
              </div>
              <div className={styles.def}>
                <dt>Sharpe ratio</dt>
                <dd>{risk.sharpe.toFixed(2)}</dd>
              </div>
              <div className={styles.def}>
                <dt>Risk band</dt>
                <dd>{risk.band}</dd>
              </div>
              <div className={styles.def}>
                <dt>Score one week ago</dt>
                <dd>{risk.previousScore}</dd>
              </div>
            </dl>
          </div>
        </Panel>
      </div>
    </>
  );
}
