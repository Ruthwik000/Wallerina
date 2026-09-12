import Button from "@/components/Button";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import { preferences, wallet } from "@/lib/data";
import { dateLabel, shortAddress } from "@/lib/format";
import SettingsForm from "./SettingsForm";
import styles from "../page.module.css";

export const metadata = { title: "Settings · Wallerina" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="The wallet Wallerina reads, the objective it optimises against, and the constraints it must respect."
      />

      <Panel
        title="Connected wallet"
        meta={`Connected ${dateLabel(wallet.connectedAt)}`}
        action={<Button variant="ghost" size="sm">Disconnect wallet</Button>}
      >
        <dl className={styles.defs}>
          <div className={`${styles.def} ${styles.defStrong}`}>
            <dt>Address</dt>
            <dd className={styles.address}>{wallet.address}</dd>
          </div>
          <div className={styles.def}>
            <dt>Label</dt>
            <dd>{wallet.label}</dd>
          </div>
          <div className={styles.def}>
            <dt>Provider</dt>
            <dd>{wallet.provider}</dd>
          </div>
          <div className={styles.def}>
            <dt>Short form</dt>
            <dd>{shortAddress(wallet.address)}</dd>
          </div>
          <div className={styles.def}>
            <dt>Access</dt>
            <dd>Read only — Wallerina never holds keys</dd>
          </div>
        </dl>
      </Panel>

      <SettingsForm preferences={preferences} networks={wallet.networks} />
    </>
  );
}
