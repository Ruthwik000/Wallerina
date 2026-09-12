"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import ConnectDialog from "@/components/ConnectDialog";
import { useWallet } from "@/components/WalletProvider";
import styles from "./landing.module.css";

export default function LandingPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { connected } = useWallet();

  return (
    <div className={styles.page}>
      <Image
        className={styles.backdrop}
        src="/background.png"
        alt=""
        fill
        priority
        sizes="100vw"
      />
      <div className={styles.veil} />

      <header className={styles.head}>
        <Link href="/" className={styles.brand} aria-label="Wallerina">
          <Image
            className={styles.logo}
            src="/logo.png"
            alt=""
            width={64}
            height={64}
            priority
          />
        </Link>
        <p className={styles.headMeta}>Portfolio risk agents</p>
      </header>

      <main className={styles.hero}>
        <h1 className={styles.title}>Wallerina</h1>
        <p className={styles.tagline}>
          Wallerina — Agents to make your wallet stable like a Ballerina
        </p>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            onClick={() => setDialogOpen(true)}
          >
            {connected ? "Change wallet" : "Connect Wallet"}
          </button>
          <Link href="/dashboard" className={styles.secondary}>
            Enter Dashboard
          </Link>
        </div>
      </main>

      <footer className={styles.foot}>
        <span>Quantitative allocation engine</span>
        <span>Monte Carlo evidence</span>
        <span>Not financial advice</span>
      </footer>

      <ConnectDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}
