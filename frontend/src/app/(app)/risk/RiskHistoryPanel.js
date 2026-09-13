"use client";

import { useEffect, useState } from "react";
import Panel from "@/components/Panel";
import LineChart from "@/components/charts/LineChart";
import { fetchRiskHistory } from "@/lib/api";
import { ratio } from "@/lib/format";
import styles from "../page.module.css";

const RECORDED_DAYS = 30;

const timeTick = (iso) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" });

export default function RiskHistoryPanel({ address }) {
  const [state, setState] = useState({ data: null, error: null });

  useEffect(() => {
    if (!address) return undefined;
    const controller = new AbortController();
    setState({ data: null, error: null });

    fetchRiskHistory(address, { recordedDays: RECORDED_DAYS, signal: controller.signal })
      .then((data) => setState({ data, error: null }))
      .catch((error) => {
        if (error.name !== "AbortError") setState({ data: null, error });
      });

    return () => controller.abort();
  }, [address]);

  const { data, error } = state;
  const formatRatio = (value) => ratio(value, { decimals: 0 });

  if (error) {
    return (
      <Panel title="Risk history">
        <p className={styles.helper}>Risk history is unavailable: {error.detail || error.message}</p>
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel title="Risk history" meta="Measuring risk over the price history">
        <p className={styles.helper}>Loading…</p>
      </Panel>
    );
  }

  const recordedVolatility = data.recorded.map((row) => ({ t: row.t, v: row.annual_volatility }));

  return (
    <div className={`${styles.grid} ${styles.split}`}>
      <Panel
        title="Volatility over time"
        meta={`Rolling ${data.rolling_window_days}-day annualised volatility · current holdings`}
      >
        {data.volatility.length < 2 ? (
          <p className={styles.helper}>
            Not enough price history for a {data.rolling_window_days}-day rolling window.
          </p>
        ) : (
          <div className={styles.stack}>
            <LineChart series={data.volatility} formatValue={formatRatio} area={false} />
            {recordedVolatility.length >= 2 ? (
              <>
                <p className={styles.statLabel}>Recorded · last {RECORDED_DAYS} days</p>
                <LineChart
                  series={recordedVolatility}
                  formatValue={formatRatio}
                  formatDate={timeTick}
                  area={false}
                  height={160}
                />
              </>
            ) : (
              <p className={styles.helper}>
                Recorded risk metrics build up as the background refresh snapshots
                this wallet.
              </p>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Drawdown over time" meta="Distance below the running peak · current holdings">
        {data.drawdown.length < 2 ? (
          <p className={styles.helper}>Not enough price history to chart drawdown.</p>
        ) : (
          <div className={styles.stack}>
            <LineChart series={data.drawdown} formatValue={formatRatio} />
            <p className={styles.helper}>
              How far today&apos;s holdings, held unchanged, sat below their previous
              high on each day. Higher is worse.
            </p>
          </div>
        )}
      </Panel>
    </div>
  );
}
