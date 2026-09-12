import Button from "@/components/Button";
import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Donut from "@/components/charts/Donut";
import LineChart from "@/components/charts/LineChart";
import { analyses, market, portfolio, recommendation, risk } from "@/lib/data";
import { dateLabel, percent, usd } from "@/lib/format";
import styles from "../page.module.css";

export const metadata = { title: "Dashboard · Wallerina" };

export default function DashboardPage() {
  const drift = recommendation.targetStablecoinRatio - portfolio.stablecoinRatio;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        description="Current exposure, the risk environment behind it, and the allocation the engine considers appropriate today."
        actions={
          <Button href="/recommendations" variant="primary">
            View recommendation
          </Button>
        }
      />

      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Portfolio value"
          value={usd(portfolio.totalValue, { decimals: 0 })}
          delta={portfolio.change24h}
          deltaLabel={`${percent(portfolio.change24h, { sign: true, decimals: 2 })} 24h`}
          size="lg"
          emphasis
        />
        <Stat
          label="Total return"
          value={usd(portfolio.totalReturn, { decimals: 0 })}
          delta={portfolio.totalReturnPct}
          deltaLabel={`${percent(portfolio.totalReturnPct, { sign: true })} all time`}
          size="lg"
        />
        <Stat
          label="Risk score"
          value={`${risk.score}`}
          delta={risk.score - risk.previousScore}
          deltaLabel={`${risk.score - risk.previousScore} vs last week`}
          note={`${risk.band} risk environment`}
          size="lg"
        />
        <Stat
          label="Market sentiment"
          value={`${market.sentiment}`}
          note={`${market.sentimentLabel} · ${market.regime}`}
          size="lg"
        />
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel
          title="Portfolio performance"
          meta="120 days · total value"
          action={
            <span className={styles.legendValue}>
              {percent(portfolio.change30d, { sign: true })} 30d
            </span>
          }
        >
          <LineChart
            series={portfolio.performance}
            formatValue={(value) => usd(value, { compact: true })}
          />
        </Panel>

        <Panel title="Stablecoin allocation" meta="Current against engine target">
          <div className={styles.stack}>
            <div className={styles.dualStat}>
              <Stat
                label="Current"
                value={percent(portfolio.stablecoinRatio)}
                note={usd(portfolio.stablecoinValue, { decimals: 0 })}
              />
              <Stat
                label="Recommended"
                value={percent(recommendation.targetStablecoinRatio, { decimals: 0 })}
                note={`Range ${recommendation.acceptableRange[0]}–${recommendation.acceptableRange[1]}%`}
                emphasis
              />
            </div>

            <Meter
              label="Stablecoins"
              value={portfolio.stablecoinRatio}
              display={percent(portfolio.stablecoinRatio)}
              secondary={recommendation.targetStablecoinRatio}
            />
            <Meter
              label="Volatile assets"
              value={portfolio.volatileRatio}
              display={percent(portfolio.volatileRatio)}
              muted
            />

            <p className={styles.helper}>
              The target sits {Math.abs(drift).toFixed(0)} points above current
              stablecoin exposure, at {recommendation.confidence}% confidence. The
              vertical mark shows the target.
            </p>
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.split}`}>
        <Panel title="Asset allocation" meta="By share of total value">
          <Donut
            segments={portfolio.allocation}
            caption={percent(portfolio.volatileRatio, { decimals: 0 })}
            captionLabel="Volatile"
          />
        </Panel>

        <Panel title="Top risk factors" meta="Weighted contribution to score">
          <div className={styles.stack}>
            {risk.factors.slice(0, 4).map((factor) => (
              <Meter
                key={factor.name}
                label={factor.name}
                value={factor.weight}
                display={`${factor.weight}% · ${factor.level}`}
              />
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Recent analysis"
        meta="Engine runs and their stance"
        flush
        action={<Button href="/recommendations" variant="quiet" size="sm">All recommendations</Button>}
      >
        <ul className={styles.feed}>
          {analyses.map((analysis) => (
            <li key={analysis.id} className={styles.feedRow}>
              <span className={styles.feedDate}>{dateLabel(analysis.date)}</span>
              <span className={styles.feedTitle}>{analysis.title}</span>
              <span className={styles.feedStance}>{analysis.stance}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  );
}
