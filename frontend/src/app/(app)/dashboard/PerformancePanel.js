"use client";

import { useEffect, useState } from "react";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import LineChart from "@/components/charts/LineChart";
import { fetchPerformanceHistory } from "@/lib/api";
import { ratio, usd } from "@/lib/format";
import styles from "../page.module.css";

const RECORDED_DAYS = 30;

const timeTick = (iso) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" });

export default function PerformancePanel({ address }) {
  const [state, setState] = useState({ data: null, error: null });

  useEffect(() => {
    if (!address) return undefined;
    const controller = new AbortController();
    setState({ data: null, error: null });

    fetchPerformanceHistory(address, { recordedDays: RECORDED_DAYS, signal: controller.signal })
      .then((data) => setState({ data, error: null }))
      .catch((error) => {
        if (error.name !== "AbortError") setState({ data: null, error });
      });

    return () => controller.abort();
  }, [address]);

  const { data, error } = state;
  const backfilled = data?.backfilled ?? [];
  const recorded = data?.recorded ?? [];

  return (
    <Panel
      title="Portfolio performance"
      meta={data ? `Current holdings over the last ${data.window_days} days` : "Valuing holdings over their price history"}
    >
      {error ? (
        <p className={styles.helper}>Performance history is unavailable: {error.detail || error.message}</p>
      ) : !data ? (
        <p className={styles.helper}>Loading price history…</p>
      ) : backfilled.length < 2 ? (
        <p className={styles.helper}>Not enough price history to chart this wallet.</p>
      ) : (
        <div className={styles.stack}>
          <Stat
            label="Total return"
            value={ratio(data.total_return, { sign: true })}
            note={`${data.window_days} days, holdings unchanged`}
            size="lg"
            emphasis
          />
          <LineChart series={backfilled} formatValue={(value) => usd(value, { compact: true })} />
          <p className={styles.helper}>
            What today&apos;s holdings would have been worth had they been held
            unchanged. It is not the wallet&apos;s actual past, which included
            trades and transfers.
            {data.excluded.length > 0 && ` Left out for lack of price history: ${data.excluded.join(", ")}.`}
          </p>

          {recorded.length >= 2 ? (
            <>
              <p className={styles.statLabel}>Recorded value · last {RECORDED_DAYS} days</p>
              <LineChart
                series={recorded}
                formatValue={(value) => usd(value, { compact: true })}
                formatDate={timeTick}
                height={180}
              />
            </>
          ) : (
            <p className={styles.helper}>
              Recorded value builds up as the background refresh snapshots this
              wallet every few minutes{recorded.length === 1 ? ` (1 snapshot so far, ${usd(recorded[0].v, { decimals: 0 })})` : ""}.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
