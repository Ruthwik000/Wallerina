"use client";

import { useWallet } from "./WalletProvider";
import { shortAddress } from "@/lib/format";
import styles from "./TopBar.module.css";

const STATUS_LABEL = {
  idle: "Not connected",
  loading: "Reading wallet",
  ready: "Live",
  error: "Unavailable",
};

export default function TopBar() {
  const { address, portfolio, status, connected, refresh, disconnect } = useWallet();

  const networks = portfolio?.chains?.map((chain) => chain.chain).join(" · ");

  return (
    <div className={styles.bar}>
      <dl className={styles.meta}>
        <div className={styles.item}>
          <dt>Wallet</dt>
          <dd>{connected ? shortAddress(address) : "—"}</dd>
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
    </div>
  );
}
