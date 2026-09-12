"use client";

import { useState } from "react";
import GoalDialog from "./GoalDialog";
import { useWallet } from "./WalletProvider";
import { shortAddress } from "@/lib/format";
import styles from "./TopBar.module.css";

const STATUS_LABEL = {
  idle: "Not connected",
  loading: "Reading wallet",
  ready: "Live",
  error: "Unavailable",
};

const GOAL_DISPLAY_LENGTH = 32;

export default function TopBar() {
  const { address, portfolio, status, connected, refresh, disconnect, goal } = useWallet();
  const [goalOpen, setGoalOpen] = useState(false);

  const networks = portfolio?.chains?.map((chain) => chain.chain).join(" · ");
  const goalText = goal
    ? goal.length > GOAL_DISPLAY_LENGTH
      ? `${goal.slice(0, GOAL_DISPLAY_LENGTH - 1)}…`
      : goal
    : "Not set";

  return (
    <div className={styles.bar}>
      <dl className={styles.meta}>
        <div className={styles.item}>
          <dt>Wallet</dt>
          <dd>{connected ? shortAddress(address) : "—"}</dd>
        </div>
        <div className={styles.item}>
          <dt>Goal</dt>
          <dd title={goal ?? undefined}>{connected ? goalText : "—"}</dd>
        </div>
        <div className={styles.item}>
          <dt>Networks</dt>
          <dd>{networks || "—"}</dd>
        </div>
        <div className={styles.item}>
          <dt>Data</dt>
          <dd>{STATUS_LABEL[status] ?? status}</dd>
        </div>
      </dl>

      {connected && (
        <div className={styles.controls}>
          <button type="button" className={styles.control} onClick={() => setGoalOpen(true)}>
            {goal ? "Change goal" : "Set goal"}
          </button>
          <button
            type="button"
            className={styles.control}
            onClick={refresh}
            disabled={status === "loading"}
          >
            {status === "loading" ? "Refreshing" : "Refresh"}
          </button>
          <button type="button" className={styles.control} onClick={disconnect}>
            Disconnect
          </button>
        </div>
      )}

      <GoalDialog open={goalOpen} onClose={() => setGoalOpen(false)} />
    </div>
  );
}
