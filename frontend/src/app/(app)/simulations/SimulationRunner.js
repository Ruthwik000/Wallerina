"use client";

import { useEffect, useRef, useState } from "react";
import Button from "@/components/Button";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import { ErrorState } from "@/components/States";
import FanChart from "@/components/charts/FanChart";
import Histogram from "@/components/charts/Histogram";
import { fetchSimulationJob, runSimulation } from "@/lib/api";
import { ratio, usd } from "@/lib/format";
import styles from "../page.module.css";

// Heavy runs are queued by the API; their result is polled for.
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

const HORIZONS = [30, 90, 180, 365];
const RUNS = [1000, 10000, 50000];

const SCENARIO_COLUMNS = [
  { key: "name", header: "Scenario" },
  { key: "stablecoin_ratio", header: "Stablecoin", align: "right" },
  { key: "expected_value", header: "Expected", align: "right" },
  { key: "p5", header: "5th percentile", align: "right" },
  { key: "expected_drawdown", header: "Expected drawdown", align: "right" },
  { key: "probability_of_loss", header: "Loss probability", align: "right" },
];

export default function SimulationRunner({ address, initial, scenarios, hasStablecoin }) {
  const [result, setResult] = useState(initial);
  const [horizon, setHorizon] = useState(initial.horizon_days);
  const [runs, setRuns] = useState(initial.simulations);
  const [stablecoinRatio, setStablecoinRatio] = useState(null);
  const [running, setRunning] = useState(false);
  const [queuedJob, setQueuedJob] = useState(null);
  const [error, setError] = useState(null);
  const controllerRef = useRef(null);

  // Stop polling if the page is left mid-run.
  useEffect(() => () => controllerRef.current?.abort(), []);

  const run = async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setRunning(true);
    setQueuedJob(null);
    setError(null);

    try {
      let next = await runSimulation(
        {
          wallet_address: address,
          horizon_days: horizon,
          simulations: runs,
          // A fixed seed keeps repeated runs comparable; only the parameters move.
          seed: 7,
          use_prediction_markets: false,
          ...(stablecoinRatio === null ? {} : { stablecoin_ratio: stablecoinRatio }),
        },
        { signal: controller.signal }
      );

      if (next.job_id) {
        setQueuedJob(next);
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        while (next.status === "queued") {
          if (Date.now() > deadline) {
            throw new Error("The queued simulation is taking longer than expected. Try again later.");
          }
          await wait(POLL_INTERVAL_MS, controller.signal);
          next = await fetchSimulationJob(next.job_id, { signal: controller.signal });
        }
        if (next.status !== "complete" || !next.result) {
          throw new Error(next.error || "The queued simulation failed.");
        }
        next = next.result;
      }

      setResult(next);
    } catch (failure) {
      if (failure.name !== "AbortError") setError(failure);
    } finally {
      if (controllerRef.current === controller) {
        setRunning(false);
        setQueuedJob(null);
      }
    }
  };

  return (
    <>
      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Expected value"
          value={usd(result.expected_value, { decimals: 0 })}
          note={`From ${usd(result.initial_value, { compact: true })} today`}
          size="lg"
          emphasis
        />
        <Stat
          label="Median value"
          value={usd(result.median_value, { decimals: 0 })}
          note="50th percentile"
          size="lg"
        />
        <Stat
          label="Probability of loss"
          value={ratio(result.probability_of_loss)}
          note="Paths ending below today"
          size="lg"
        />
        <Stat
          label="Expected drawdown"
          value={ratio(result.expected_drawdown)}
          note="Mean peak-to-trough"
          size="lg"
        />
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel
          title="Simulated paths"
          meta={`${result.simulations.toLocaleString("en-US")} paths · ${result.horizon_days} days · ${ratio(result.stablecoin_ratio)} stablecoin`}
        >
          <FanChart
            paths={result.fan.map((band) => ({
              t: String(band.day),
              p5: band.p5,
              p25: band.p25,
              median: band.median,
              p75: band.p75,
              p95: band.p95,
            }))}
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

        <Panel title="Controls" meta="Re-run against the live wallet">
          <div className={styles.stack}>
            <fieldset className={styles.fieldset}>
              <legend className={styles.legend}>Time horizon</legend>
              <div className={styles.choices}>
                {HORIZONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`${styles.choice} ${horizon === option ? styles.choiceActive : ""}`}
                    aria-pressed={horizon === option}
                    onClick={() => setHorizon(option)}
                  >
                    {option}d
                  </button>
                ))}
              </div>
            </fieldset>

            <fieldset className={styles.fieldset}>
              <legend className={styles.legend}>Number of simulations</legend>
              <div className={styles.choices}>
                {RUNS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`${styles.choice} ${runs === option ? styles.choiceActive : ""}`}
                    aria-pressed={runs === option}
                    onClick={() => setRuns(option)}
                  >
                    {option.toLocaleString("en-US")}
                  </button>
                ))}
              </div>
            </fieldset>

            <fieldset className={styles.fieldset}>
              <legend className={styles.legend}>Stablecoin allocation</legend>
              <div className={styles.choices}>
                <button
                  type="button"
                  className={`${styles.choice} ${stablecoinRatio === null ? styles.choiceActive : ""}`}
                  aria-pressed={stablecoinRatio === null}
                  onClick={() => setStablecoinRatio(null)}
                >
                  Current
                </button>
                {[0.25, 0.5, 0.75].map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`${styles.choice} ${stablecoinRatio === option ? styles.choiceActive : ""}`}
                    aria-pressed={stablecoinRatio === option}
                    onClick={() => setStablecoinRatio(option)}
                    disabled={!hasStablecoin}
                    title={hasStablecoin ? undefined : "This wallet holds no recognised stablecoin"}
                  >
                    {option * 100}%
                  </button>
                ))}
              </div>
            </fieldset>

            <dl className={styles.defs}>
              <div className={styles.def}>
                <dt>Model</dt>
                <dd>Correlated GBM</dd>
              </div>
              <div className={styles.def}>
                <dt>Drift assumption</dt>
                <dd>{result.drift_mode === "zero" ? "Zero expected return" : result.drift_mode}</dd>
              </div>
              <div className={styles.def}>
                <dt>Volatility multiplier</dt>
                <dd>×{result.volatility_multiplier.toFixed(2)}</dd>
              </div>
              <div className={styles.def}>
                <dt>Rebalancing</dt>
                <dd>None within horizon</dd>
              </div>
            </dl>

            <Button variant="primary" full onClick={run} disabled={running}>
              {running ? (queuedJob ? "Queued on the worker" : "Running") : "Run simulation"}
            </Button>

            {queuedJob && (
              <p className={styles.helper}>
                {runs.toLocaleString("en-US")} paths over {horizon} days is a heavy run,
                so it was queued (job {queuedJob.job_id.slice(0, 8)}). Checking for the
                result every {POLL_INTERVAL_MS / 1000} seconds.
              </p>
            )}

            {error && <ErrorState error={error} title="Simulation failed" />}
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.splitWide}`}>
        <Panel title="Distribution of outcomes" meta="Terminal value across all paths">
          <Histogram
            bins={result.distribution.map((bin) => ({
              from: bin.lower,
              to: bin.upper,
              count: bin.count,
            }))}
            threshold={result.initial_value}
            markers={[
              { label: "P5", value: result.p5 },
              { label: "Median", value: result.median_value },
              { label: "P95", value: result.p95 },
            ]}
            formatValue={(value) => usd(value, { compact: true })}
          />
          <p className={styles.helper}>
            Muted bins fall below today&apos;s value. {ratio(result.probability_of_loss)} of
            paths finish there.
          </p>
        </Panel>

        <Panel title="Outcome range" meta="Percentiles of terminal value">
          <dl className={styles.defs}>
            <div className={`${styles.def} ${styles.defStrong}`}>
              <dt>Best simulated path</dt>
              <dd>{usd(result.best_case, { decimals: 0 })}</dd>
            </div>
            <div className={styles.def}>
              <dt>95th percentile</dt>
              <dd>{usd(result.p95, { decimals: 0 })}</dd>
            </div>
            <div className={styles.def}>
              <dt>Median</dt>
              <dd>{usd(result.median_value, { decimals: 0 })}</dd>
            </div>
            <div className={styles.def}>
              <dt>5th percentile</dt>
              <dd>{usd(result.p5, { decimals: 0 })}</dd>
            </div>
            <div className={`${styles.def} ${styles.defStrong}`}>
              <dt>Worst simulated path</dt>
              <dd>{usd(result.worst_case, { decimals: 0 })}</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <Panel
        title="Scenario comparison"
        meta="Same horizon and identical market draws, different stablecoin ratios"
        flush
      >
        <Table
          columns={SCENARIO_COLUMNS}
          rows={scenarios}
          rowKey={(scenario) => scenario.name}
          renderCell={(scenario, column) => {
            switch (column.key) {
              case "stablecoin_ratio":
                return ratio(scenario.stablecoin_ratio, { decimals: 1 });
              case "expected_value":
              case "p5":
                return usd(scenario[column.key], { decimals: 0 });
              case "expected_drawdown":
              case "probability_of_loss":
                return ratio(scenario[column.key]);
              default:
                return scenario.name;
            }
          }}
        />
      </Panel>
    </>
  );
}
