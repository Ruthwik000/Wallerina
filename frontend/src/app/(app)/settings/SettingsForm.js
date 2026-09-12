"use client";

import { useState } from "react";
import Button from "@/components/Button";
import Panel from "@/components/Panel";
import Toggle from "@/components/Toggle";
import styles from "../page.module.css";

/* Local state only — preferences post to the backend once the API exists. */
export default function SettingsForm({ preferences, networks }) {
  const [objective, setObjective] = useState(preferences.riskObjective);
  const [horizon, setHorizon] = useState(preferences.horizon);
  const [maxDrawdown, setMaxDrawdown] = useState(preferences.maxDrawdown);
  const [stablecoins, setStablecoins] = useState(preferences.stablecoins);
  const [analysis, setAnalysis] = useState(preferences.analysis);
  const [notifications, setNotifications] = useState(preferences.notifications);
  const [enabledNetworks, setEnabledNetworks] = useState(networks);

  const toggleIn = (list, setList, key) =>
    setList(
      list.map((item) =>
        (item.key ?? item.symbol ?? item.id) === key
          ? { ...item, enabled: !item.enabled }
          : item
      )
    );

  return (
    <>
      <div className={`${styles.grid} ${styles.cols2}`}>
        <Panel title="Risk objective" meta="Drives the target allocation range">
          <div className={styles.stack}>
            <div className={styles.choices}>
              {preferences.riskObjectives.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`${styles.choice} ${objective === option ? styles.choiceActive : ""}`}
                  aria-pressed={objective === option}
                  onClick={() => setObjective(option)}
                >
                  {option}
                </button>
              ))}
            </div>
            <p className={styles.helper}>
              Capital preservation pulls the target stablecoin ratio upward and
              tightens the acceptable range. Growth does the opposite.
            </p>
          </div>
        </Panel>

        <Panel title="Investment horizon" meta="Simulation and rebalance window">
          <div className={styles.stack}>
            <div className={styles.choices}>
              {preferences.horizons.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`${styles.choice} ${horizon === option ? styles.choiceActive : ""}`}
                  aria-pressed={horizon === option}
                  onClick={() => setHorizon(option)}
                >
                  {option}
                </button>
              ))}
            </div>
            <p className={styles.helper}>
              Shorter horizons weight realised volatility more heavily than trend.
            </p>
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.split}`}>
        <Panel title="Maximum acceptable drawdown" meta="Hard constraint on the allocation engine">
          <div className={styles.stack}>
            <div className={styles.sliderHead}>
              <span className={styles.sliderValue}>{maxDrawdown}%</span>
              <span className={styles.sliderRange}>5% — 50%</span>
            </div>
            <input
              className={styles.slider}
              type="range"
              min={5}
              max={50}
              step={1}
              value={maxDrawdown}
              onChange={(event) => setMaxDrawdown(Number(event.target.value))}
              aria-label="Maximum acceptable drawdown"
            />
            <p className={styles.helper}>
              Allocations whose simulated drawdown exceeds this limit are rejected
              before a recommendation is produced.
            </p>
          </div>
        </Panel>

        <Panel title="Stablecoin preferences" meta="Issuers eligible for rebalancing">
          <div>
            {stablecoins.map((coin) => (
              <Toggle
                key={coin.symbol}
                id={`stable-${coin.symbol}`}
                label={coin.symbol}
                checked={coin.enabled}
                onChange={() => toggleIn(stablecoins, setStablecoins, coin.symbol)}
              />
            ))}
          </div>
        </Panel>
      </div>

      <div className={`${styles.grid} ${styles.cols2}`}>
        <Panel title="Analysis preferences" meta="How the engine runs">
          <div>
            {analysis.map((item) => (
              <Toggle
                key={item.key}
                id={`analysis-${item.key}`}
                label={item.name}
                description={item.description}
                checked={item.enabled}
                onChange={() => toggleIn(analysis, setAnalysis, item.key)}
              />
            ))}
          </div>
        </Panel>

        <Panel title="Notification settings" meta="When Wallerina contacts you">
          <div>
            {notifications.map((item) => (
              <Toggle
                key={item.key}
                id={`notify-${item.key}`}
                label={item.name}
                description={item.description}
                checked={item.enabled}
                onChange={() => toggleIn(notifications, setNotifications, item.key)}
              />
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Supported networks"
        meta="Chains scanned when reading the wallet"
        action={<Button variant="quiet" size="sm">Rescan wallet</Button>}
      >
        <div>
          {enabledNetworks.map((network) => (
            <Toggle
              key={network.id}
              id={`network-${network.id}`}
              label={network.name}
              description={
                network.assets > 0
                  ? `${network.assets} assets detected`
                  : "No assets detected"
              }
              checked={network.enabled}
              onChange={() => toggleIn(enabledNetworks, setEnabledNetworks, network.id)}
            />
          ))}
        </div>
      </Panel>
    </>
  );
}
