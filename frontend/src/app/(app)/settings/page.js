"use client";

import { useState } from "react";
import Button from "@/components/Button";
import ConnectDialog from "@/components/ConnectDialog";
import GoalDialog from "@/components/GoalDialog";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import { Disconnected } from "@/components/States";
import { useWallet } from "@/components/WalletProvider";
import { API_BASE } from "@/lib/api";
import { shortAddress } from "@/lib/format";
import styles from "../page.module.css";

const NETWORKS = [
  { id: "eth-mainnet", name: "Ethereum" },
  { id: "base-mainnet", name: "Base" },
  { id: "arb-mainnet", name: "Arbitrum" },
  { id: "matic-mainnet", name: "Polygon" },
];

export default function SettingsPage() {
  const { address, portfolio, connected, restored, disconnect, goal, goalPersisted } = useWallet();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [goalOpen, setGoalOpen] = useState(false);

  if (!restored) return null;

  const header = (
    <PageHeader
      eyebrow="Account"
      title="Settings"
      description="The wallet Wallerina is reading, its goal and the networks it scans."
    />
  );

  if (!connected) {
    return (
      <>
        {header}
        <Disconnected />
        <ConnectDialog
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          redirectTo="/settings"
        />
      </>
    );
  }

  const active = new Set(portfolio?.chains?.map((chain) => chain.network) ?? []);

  return (
    <>
      {header}

      <Panel
        title="Connected wallet"
        meta="Read-only — Wallerina never holds keys"
        action={
          <div className={styles.headerActions}>
            <Button variant="ghost" size="sm" onClick={() => setDialogOpen(true)}>
              Change
            </Button>
            <Button variant="ghost" size="sm" onClick={disconnect}>
              Disconnect
            </Button>
          </div>
        }
      >
        <dl className={styles.defs}>
          <div className={`${styles.def} ${styles.defStrong}`}>
            <dt>Address</dt>
            <dd className={styles.address}>{address}</dd>
          </div>
          <div className={styles.def}>
            <dt>Short form</dt>
            <dd>{shortAddress(address)}</dd>
          </div>
          <div className={styles.def}>
            <dt>Access</dt>
            <dd>Public balances only — no key, seed phrase or signature</dd>
          </div>
          <div className={styles.def}>
            <dt>Positions found</dt>
            <dd>
              {portfolio
                ? `${portfolio.holdings_kept} kept of ${portfolio.holdings_scanned.toLocaleString("en-US")} scanned`
                : "—"}
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel title="Supported networks" meta="Scanned on every read">
        <dl className={styles.defs}>
          {NETWORKS.map((network) => (
            <div key={network.id} className={styles.def}>
              <dt>{network.name}</dt>
              <dd>{active.has(network.id) ? "Holdings found" : "No holdings"}</dd>
            </div>
          ))}
        </dl>
      </Panel>

      <Panel title="Backend" meta="Where this data comes from">
        <dl className={styles.defs}>
          <div className={styles.def}>
            <dt>API</dt>
            <dd className={styles.address}>{API_BASE}</dd>
          </div>
          <div className={styles.def}>
            <dt>Balances and prices</dt>
            <dd>Alchemy</dd>
          </div>
          <div className={styles.def}>
            <dt>Prediction markets</dt>
            <dd>Polymarket</dd>
          </div>
        </dl>
      </Panel>

      <Panel
        title="Goal"
        meta="Sets the rules every agent works within"
        action={
          <Button variant="ghost" size="sm" onClick={() => setGoalOpen(true)}>
            {goal ? "Change" : "Set goal"}
          </Button>
        }
      >
        <dl className={styles.defs}>
          <div className={`${styles.def} ${styles.defStrong}`}>
            <dt>Current goal</dt>
            <dd>{goal ?? "Not set"}</dd>
          </div>
          <div className={styles.def}>
            <dt>Stored</dt>
            <dd>
              {!goal ? "—" : goalPersisted ? "Saved to the database" : "Saved in this browser"}
            </dd>
          </div>
        </dl>
      </Panel>

      <ConnectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        redirectTo="/settings"
      />
      <GoalDialog open={goalOpen} onClose={() => setGoalOpen(false)} />
    </>
  );
}
