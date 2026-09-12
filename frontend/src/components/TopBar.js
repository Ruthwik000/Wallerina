import { shortAddress, timeLabel } from "@/lib/format";
import { wallet } from "@/lib/data";
import styles from "./TopBar.module.css";

export default function TopBar({ lastAnalysis }) {
  const activeNetworks = wallet.networks.filter((network) => network.enabled);

  return (
    <div className={styles.bar}>
      <dl className={styles.meta}>
        <div className={styles.item}>
          <dt>Wallet</dt>
          <dd>{shortAddress(wallet.address)}</dd>
        </div>
        <div className={styles.item}>
          <dt>Networks</dt>
          <dd>{activeNetworks.map((network) => network.name).join(" · ")}</dd>
        </div>
        <div className={styles.item}>
          <dt>Last analysis</dt>
          <dd>{timeLabel(lastAnalysis)}</dd>
        </div>
      </dl>
    </div>
  );
}
