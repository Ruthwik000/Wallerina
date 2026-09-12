"use client";

import Button from "@/components/Button";
import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import Panel from "@/components/Panel";
import Table from "@/components/Table";
import { useWallet } from "@/components/WalletProvider";
import { ratio, usd } from "@/lib/format";
import styles from "../page.module.css";

const COLUMNS = [
  { key: "name", header: "Allocation" },
  { key: "stablecoin_ratio", header: "Stablecoin", align: "right" },
  { key: "expected_value", header: "Expected", align: "right" },
  { key: "p5", header: "5th percentile", align: "right" },
  { key: "expected_drawdown", header: "Expected drawdown", align: "right" },
  { key: "probability_of_loss", header: "Loss probability", align: "right" },
];

export default function RecommendationsPage() {
  const { scenarios, portfolio, simulation } = useWallet();

  const header = (
    <PageHeader
      eyebrow="Analysis"
      title="Recommendations"
      description="The allocation engine that turns this evidence into a target is not built yet. What follows is the evidence it will decide from."
      actions={
        <Button href="/chat" variant="ghost">
          Ask about these numbers
        </Button>
      }
    />
  );

  return (
    <PageState header={header} loadingLabel="Gathering evidence">
      {() => {
        const rows = scenarios ?? [];

        // The best available stand-in for a recommendation: the allocation with
        // the strongest downside, which is what the engine will optimise for.
        const bestDownside = rows.reduce(
          (best, row) => (best === null || row.p5 > best.p5 ? row : best),
          null
        );

        return (
          <>
            <Panel title="Why there is no recommendation yet" meta="Scope of the current build">
              <div className={styles.prose}>
                <p>
                  Wallerina&apos;s design deliberately separates the quantitative
                  engine from the allocation decision. The engine — wallet
                  ingestion, classification, risk measurement and Monte Carlo — is
                  built and is producing the numbers on this page from live data.
                </p>
                <p>
                  The goal layer, the analysis agents and the allocation engine
                  that convert those numbers into a target stablecoin ratio are
                  not implemented. Rather than print a figure no model produced,
                  this page shows the simulated consequences of each allocation
                  and leaves the judgement to you.
                </p>
              </div>
            </Panel>

            <Panel
              title="Allocation evidence"
              meta={`${simulation.horizon_days}-day horizon · identical market draws across rows`}
              flush
            >
              {rows.length === 0 ? (
                <p className={styles.helper}>
                  No scenarios available. This wallet holds no recognised
                  stablecoin, so there is nothing to rotate capital into.
                </p>
              ) : (
                <Table
                  columns={COLUMNS}
                  rows={rows}
                  rowKey={(row) => row.name}
                  renderCell={(row, column) => {
                    switch (column.key) {
                      case "stablecoin_ratio":
                        return ratio(row.stablecoin_ratio, { decimals: 1 });
                      case "expected_value":
                      case "p5":
                        return usd(row[column.key], { decimals: 0 });
                      case "expected_drawdown":
                      case "probability_of_loss":
                        return ratio(row[column.key]);
                      default:
                        return row.name;
                    }
                  }}
                />
              )}
            </Panel>

            {bestDownside && (
              <div className={`${styles.grid} ${styles.split}`}>
                <Panel title="What the evidence shows" meta="Read directly from the table">
                  <div className={styles.prose}>
                    <p>
                      Of the allocations simulated, {bestDownside.name.toLowerCase()}{" "}
                      produces the strongest 5th-percentile outcome at{" "}
                      {usd(bestDownside.p5, { decimals: 0 })}, with an expected
                      drawdown of {ratio(bestDownside.expected_drawdown)}.
                    </p>
                    <p>
                      Because the simulator assumes zero expected return, expected
                      values barely differ between allocations — the entire
                      difference is in the downside. That is the trade the
                      allocation engine will eventually have to price against your
                      stated goal and horizon.
                    </p>
                  </div>
                </Panel>

                <Panel title="Current position" meta="For comparison">
                  <dl className={styles.defs}>
                    <div className={`${styles.def} ${styles.defStrong}`}>
                      <dt>Current stablecoin ratio</dt>
                      <dd>{ratio(portfolio.stablecoin_ratio)}</dd>
                    </div>
                    <div className={styles.def}>
                      <dt>Current 5th percentile</dt>
                      <dd>{usd(simulation.p5, { decimals: 0 })}</dd>
                    </div>
                    <div className={styles.def}>
                      <dt>Current expected drawdown</dt>
                      <dd>{ratio(simulation.expected_drawdown)}</dd>
                    </div>
                    <div className={styles.def}>
                      <dt>Current loss probability</dt>
                      <dd>{ratio(simulation.probability_of_loss)}</dd>
                    </div>
                  </dl>
                </Panel>
              </div>
            )}
          </>
        );
      }}
    </PageState>
  );
}
