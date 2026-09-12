import Button from "@/components/Button";
import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import { market, portfolio, recommendation, risk, simulation } from "@/lib/data";
import { dateLabel, percent, quantity, usd } from "@/lib/format";
import styles from "../page.module.css";

export const metadata = { title: "Recommendations · Wallerina" };

const TRADE_COLUMNS = [
  { key: "action", header: "Action" },
  { key: "asset", header: "Asset" },
  { key: "quantity", header: "Quantity", align: "right" },
  { key: "value", header: "Value", align: "right" },
  { key: "note", header: "Rationale", align: "right" },
];

export default function RecommendationsPage() {
  const difference =
    recommendation.targetStablecoinRatio - recommendation.currentStablecoinRatio;
  const sells = recommendation.trades.filter((trade) => trade.action === "Sell");
  const buys = recommendation.trades.filter((trade) => trade.action === "Buy");
  const rotated = sells.reduce((sum, trade) => sum + trade.value, 0);

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="Recommendations"
        description={`Generated ${dateLabel(recommendation.generatedAt)} from the current book, the risk environment and ${simulation.defaults.runs.toLocaleString("en-US")} simulated paths.`}
        actions={
          <>
            <Button variant="ghost">Download report</Button>
            <Button variant="primary">Execute rebalance</Button>
          </>
        }
      />

      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Recommended stablecoin allocation"
          value={percent(recommendation.targetStablecoinRatio, { decimals: 0 })}
          note={`Acceptable range ${recommendation.acceptableRange[0]}–${recommendation.acceptableRange[1]}% · confidence ${recommendation.confidence}%`}
          size="lg"
          emphasis
        />
        <Stat
          label="Current allocation"
          value={percent(recommendation.currentStablecoinRatio)}
          note={usd(portfolio.stablecoinValue, { decimals: 0 })}
          size="lg"
        />
        <Stat
          label="Allocation difference"
          value={percent(difference, { sign: true })}
          note={`${usd((Math.abs(difference) / 100) * portfolio.totalValue, { compact: true })} to rotate`}
          size="lg"
        />
        <Stat
          label="Action"
          value={recommendation.action}
          note={`${recommendation.trades.length} trades across ${new Set(recommendation.trades.map((t) => t.asset)).size} assets`}
          size="lg"
        />
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel title="Rebalancing preview" meta="Current against target allocation">
          <div className={styles.stack}>
            <Meter
              label="Stablecoins — current"
              value={recommendation.currentStablecoinRatio}
              display={percent(recommendation.currentStablecoinRatio)}
              secondary={recommendation.targetStablecoinRatio}
              muted
            />
            <Meter
              label="Stablecoins — target"
              value={recommendation.targetStablecoinRatio}
              display={percent(recommendation.targetStablecoinRatio, { decimals: 0 })}
            />
            <Meter
              label="Volatile assets — after rebalance"
              value={100 - recommendation.targetStablecoinRatio}
              display={percent(100 - recommendation.targetStablecoinRatio, { decimals: 0 })}
              muted
            />

            <dl className={styles.defs}>
              <div className={styles.def}>
                <dt>Capital rotated into stablecoins</dt>
                <dd>{usd(rotated, { decimals: 0 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>Assets to sell</dt>
                <dd>{sells.map((trade) => trade.asset).join(" · ")}</dd>
              </div>
              <div className={styles.def}>
                <dt>Stablecoins to buy</dt>
                <dd>{buys.map((trade) => trade.asset).join(" · ")}</dd>
              </div>
              <div className={styles.def}>
                <dt>Assets to hold</dt>
                <dd>{recommendation.holds.join(" · ")}</dd>
              </div>
            </dl>
          </div>
        </Panel>

        <Panel title="Expected outcome after rebalance" meta="Against the current book">
          <div className={styles.stack}>
            <div className={styles.outcomeGrid}>
              <Stat
                label="Risk score"
                value={`${recommendation.expectedRiskAfter}`}
                deltaLabel={`from ${risk.score}`}
                delta={recommendation.expectedRiskAfter - risk.score}
                emphasis
              />
              <Stat
                label="Expected return"
                value={percent(recommendation.expectedReturnAfter, { sign: true })}
                deltaLabel="annualised"
              />
              <Stat
                label="Expected drawdown"
                value={percent(recommendation.expectedDrawdownAfter)}
                delta={recommendation.expectedDrawdownAfter - simulation.expectedDrawdown}
                deltaLabel={`from ${percent(simulation.expectedDrawdown)}`}
              />
              <Stat
                label="Loss probability"
                value={percent(29.6)}
                delta={29.6 - simulation.probabilityOfLoss}
                deltaLabel={`from ${percent(simulation.probabilityOfLoss)}`}
              />
            </div>

            <p className={styles.helper}>
              The rebalance trades {percent(1.8)} of expected terminal value for a
              materially tighter downside: expected drawdown falls by nearly half
              and the 5th percentile outcome improves by{" "}
              {usd(118430 - simulation.p5, { compact: true })}.
            </p>
          </div>
        </Panel>
      </div>

      <Panel title="Recommended trades" meta="Ordered for execution" flush>
        <Table
          columns={TRADE_COLUMNS}
          rows={recommendation.trades}
          rowKey={(trade) => `${trade.action}-${trade.asset}`}
          renderCell={(trade, column) => {
            switch (column.key) {
              case "action":
                return <span className={styles.txType}>{trade.action}</span>;
              case "quantity":
                return quantity(trade.quantity, trade.asset);
              case "value":
                return usd(trade.value, { decimals: 0 });
              case "note":
                return <span className={styles.tradeNote}>{trade.note}</span>;
              default:
                return trade[column.key];
            }
          }}
        />
      </Panel>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel title="Recommendation reasoning" meta="Why the engine reached this allocation">
          <div className={styles.prose}>
            {recommendation.reasoning.map((paragraph) => (
              <p key={paragraph.slice(0, 24)}>{paragraph}</p>
            ))}
          </div>
        </Panel>

        <div className={styles.stackWide}>
          <Panel title="Market signals" meta={`${market.regime} · sentiment ${market.sentiment}`} flush>
            <ul className={styles.indicators}>
              {market.signals.map((signal) => (
                <li key={signal.name} className={styles.signal}>
                  <span className={styles.indicatorName}>{signal.name}</span>
                  <span className={styles.indicatorValue}>{signal.reading}</span>
                  <span className={styles.indicatorDelta}>{signal.stance}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Monte Carlo evidence" meta="Inputs behind the decision">
            <dl className={styles.defs}>
              {recommendation.evidence.map((item) => (
                <div key={item.label} className={styles.def}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </>
  );
}
