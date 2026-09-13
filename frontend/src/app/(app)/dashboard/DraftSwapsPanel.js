"use client";

import { useEffect, useRef, useState } from "react";
import Button from "@/components/Button";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import { fetchDraftSwaps } from "@/lib/api";
import { quantity, ratio, timeLabel, usd } from "@/lib/format";
import styles from "../page.module.css";

const COLUMNS = [
  { key: "chain", header: "Network" },
  { key: "sell", header: "Sell" },
  { key: "value", header: "Value", align: "right" },
  { key: "buy", header: "Swap into" },
  { key: "reason", header: "Why" },
];

/* Base units to a display number. Precision loss is fine for display. */
const tokenAmount = (units, decimals) => Number(units) / 10 ** decimals;

export default function DraftSwapsPanel({ address, goal }) {
  const [state, setState] = useState({ status: "idle", plan: null, error: null });
  const controller = useRef(null);

  // A different wallet or goal makes any drafts on screen stale.
  useEffect(() => {
    controller.current?.abort();
    setState({ status: "idle", plan: null, error: null });
  }, [address, goal]);

  useEffect(() => () => controller.current?.abort(), []);

  const build = () => {
    controller.current?.abort();
    controller.current = new AbortController();
    setState((previous) => ({ ...previous, status: "loading", error: null }));

    fetchDraftSwaps(address, { goal, signal: controller.current.signal })
      .then((plan) => setState({ status: "ready", plan, error: null }))
      .catch((error) => {
        if (error.name !== "AbortError") setState({ status: "error", plan: null, error });
      });
  };

  const { status, plan, error } = state;
  const loading = status === "loading";
  const totalUsd = plan?.legs.reduce((sum, leg) => sum + leg.sell_value_usd, 0) ?? 0;

  return (
    <Panel
      title="Draft swaps"
      meta="Drafts only · Wallerina never signs, sends or executes anything"
      action={
        <Button variant={plan ? "ghost" : "primary"} size="sm" onClick={build} disabled={loading}>
          {loading ? "Drafting…" : plan ? "Redraft" : "Draft swaps"}
        </Button>
      }
    >
      {status === "idle" && (
        <p className={styles.helper}>
          Turns the current recommendation into the concrete swaps it implies,
          one per network, so you can see exactly what a rebalance would involve.
          Nothing is quoted, signed or sent.
        </p>
      )}

      {loading && !plan && <p className={styles.helper}>Running a fresh recommendation…</p>}

      {status === "error" && (
        <p className={styles.helper}>Drafts are unavailable: {error.detail || error.message}</p>
      )}

      {plan && (
        <>
          <div className={`${styles.statRow} ${styles.statRow3}`}>
            <Stat
              label="Stablecoins now"
              value={ratio(plan.current_stablecoin_ratio)}
              note={`Target ${ratio(plan.target_stablecoin_ratio)}`}
            />
            <Stat
              label="Swaps drafted"
              value={String(plan.legs.length)}
              note={plan.legs.length ? `${usd(totalUsd, { decimals: 0 })} in total` : "Nothing to move"}
            />
            <Stat
              label="Drafted"
              value={timeLabel(plan.generated_at)}
              note={`Goal: ${plan.goal}`}
            />
          </div>

          {plan.legs.length === 0 ? (
            <p className={styles.helper}>
              {plan.rebalance_required
                ? "A rebalance is recommended, but none of it can be expressed as a same-network swap."
                : "The wallet is within its acceptable range, so no swaps are drafted."}
            </p>
          ) : (
            <Table
              columns={COLUMNS}
              rows={plan.legs}
              rowKey={(leg) => leg.id}
              renderCell={(leg, column) => {
                switch (column.key) {
                  case "chain":
                    return leg.chain;
                  case "sell":
                    return (
                      <span className={styles.assetCell}>
                        <span className={styles.assetSymbol}>{leg.sell_symbol}</span>
                        <span className={styles.assetName}>
                          {quantity(tokenAmount(leg.sell_amount, leg.sell_decimals), leg.sell_symbol)}
                        </span>
                      </span>
                    );
                  case "value":
                    return usd(leg.sell_value_usd, { decimals: 0 });
                  case "buy":
                    return <span className={styles.assetSymbol}>{leg.buy_symbol}</span>;
                  default:
                    return leg.reason;
                }
              }}
            />
          )}

          {plan.skipped.length > 0 && (
            <ul className={styles.caveats}>
              {plan.skipped.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  );
}
