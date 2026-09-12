import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import FanChart from "@/components/charts/FanChart";
import Histogram from "@/components/charts/Histogram";
import { portfolio, simulation } from "@/lib/data";
import { percent, usd } from "@/lib/format";
import SimulationControls from "./SimulationControls";
import styles from "../page.module.css";

export const metadata = { title: "Simulations · Wallerina" };

const SCENARIO_COLUMNS = [
  { key: "name", header: "Scenario" },
  { key: "stablecoin", header: "Stablecoin", align: "right" },
  { key: "expected", header: "Expected value", align: "right" },
  { key: "p5", header: "5th percentile", align: "right" },
  { key: "drawdown", header: "Expected drawdown", align: "right" },
  { key: "lossProb", header: "Loss probability", align: "right" },
];

export default function SimulationsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="Simulations"
        description={`Monte Carlo over ${simulation.defaults.runs.toLocaleString("en-US")} paths at a ${simulation.defaults.horizonDays} day horizon, holding the current allocation fixed.`}
      />

      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Expected portfolio value"
          value={usd(simulation.expectedValue, { decimals: 0 })}
          note={`From ${usd(portfolio.totalValue, { compact: true })} today`}
          size="lg"
          emphasis
        />
        <Stat label="Median portfolio value" value={usd(simulation.medianValue, { decimals: 0 })} note="50th percentile" size="lg" />
        <Stat label="Probability of loss" value={percent(simulation.probabilityOfLoss)} note="Paths ending below today" size="lg" />
        <Stat label="Expected drawdown" value={percent(simulation.expectedDrawdown)} note="Mean peak-to-trough" size="lg" />
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel
          title="Monte Carlo simulation"
          meta="Median path with 25–75 and 5–95 percentile bands"
        >
          <FanChart
            paths={simulation.fan}
            formatValue={(value) => usd(value, { compact: true })}
          />
          <div className={styles.bandLegend}>
            <span className={styles.bandItem}>
              <span className={styles.bandSwatchLine} /> Median
            </span>
            <span className={styles.bandItem}>
              <span className={styles.bandSwatchInner} /> 25–75 percentile
            </span>
            <span className={styles.bandItem}>
              <span className={styles.bandSwatchOuter} /> 5–95 percentile
            </span>
          </div>
        </Panel>

        <Panel title="Simulation controls" meta="Parameters for the next run">
          <SimulationControls
            defaults={simulation.defaults}
            stablecoinRatio={portfolio.stablecoinRatio}
          />
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel
          title="Simulated portfolio distribution"
          meta="Terminal value across all paths"
        >
          <Histogram
            bins={simulation.distribution}
            threshold={portfolio.totalValue}
            markers={[
              { label: "P5", value: simulation.p5 },
              { label: "Median", value: simulation.medianValue },
              { label: "P95", value: simulation.p95 },
            ]}
            formatValue={(value) => usd(value, { compact: true })}
          />
          <p className={styles.helper}>
            Muted bins fall below today&apos;s portfolio value. {percent(simulation.probabilityOfLoss)} of
            paths finish in that region.
          </p>
        </Panel>

        <Panel title="Outcome range" meta="Percentiles of terminal value">
          <div className={styles.stack}>
            <dl className={styles.defs}>
              <div className={`${styles.def} ${styles.defStrong}`}>
                <dt>Best case</dt>
                <dd>{usd(simulation.bestCase, { decimals: 0 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>95th percentile</dt>
                <dd>{usd(simulation.p95, { decimals: 0 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>Median</dt>
                <dd>{usd(simulation.medianValue, { decimals: 0 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>5th percentile</dt>
                <dd>{usd(simulation.p5, { decimals: 0 })}</dd>
              </div>
              <div className={`${styles.def} ${styles.defStrong}`}>
                <dt>Worst case</dt>
                <dd>{usd(simulation.worstCase, { decimals: 0 })}</dd>
              </div>
            </dl>
            <p className={styles.helper}>
              The spread between the 5th and 95th percentile is{" "}
              {usd(simulation.p95 - simulation.p5, { compact: true })} — roughly{" "}
              {percent(((simulation.p95 - simulation.p5) / portfolio.totalValue) * 100, { decimals: 0 })}{" "}
              of the book at the current allocation.
            </p>
          </div>
        </Panel>
      </div>

      <Panel title="Scenario comparison" meta="Same horizon, different stablecoin ratios" flush>
        <Table
          columns={SCENARIO_COLUMNS}
          rows={simulation.scenarios}
          rowKey={(scenario) => scenario.name}
          renderCell={(scenario, column) => {
            switch (column.key) {
              case "stablecoin":
                return percent(scenario.stablecoin, { decimals: 0 });
              case "expected":
              case "p5":
                return usd(scenario[column.key], { decimals: 0 });
              case "drawdown":
              case "lossProb":
                return percent(scenario[column.key]);
              default:
                return scenario.name;
            }
          }}
        />
      </Panel>
    </>
  );
}
