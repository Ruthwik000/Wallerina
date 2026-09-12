"use client";

import { useState } from "react";
import Button from "@/components/Button";
import styles from "../page.module.css";

const HORIZONS = [30, 90, 180, 365];
const RUNS = [1000, 10000, 50000];

/* Controls are presentational until the engine endpoint exists: they hold the
   parameters and report them upward, and "Run simulation" replays the chart. */
export default function SimulationControls({ defaults, stablecoinRatio, onRun }) {
  const [horizon, setHorizon] = useState(defaults.horizonDays);
  const [runs, setRuns] = useState(defaults.runs);
  const [running, setRunning] = useState(false);

  const run = () => {
    setRunning(true);
    onRun?.({ horizon, runs });
    window.setTimeout(() => setRunning(false), 700);
  };

  return (
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

      <dl className={styles.defs}>
        <div className={styles.def}>
          <dt>Current allocation</dt>
          <dd>{stablecoinRatio.toFixed(1)}% stablecoin</dd>
        </div>
        <div className={styles.def}>
          <dt>Model</dt>
          <dd>Correlated GBM</dd>
        </div>
        <div className={styles.def}>
          <dt>Rebalancing</dt>
          <dd>None within horizon</dd>
        </div>
      </dl>

      <Button variant="primary" full onClick={run} disabled={running}>
        {running ? "Running" : "Run simulation"}
      </Button>
    </div>
  );
}
