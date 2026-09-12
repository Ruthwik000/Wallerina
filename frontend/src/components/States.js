"use client";

import Link from "next/link";
import styles from "./States.module.css";

/* Real data can be slow, absent or broken, so every page needs these three
   states. They share one visual language: a bordered panel, a short label and
   one sentence of plain explanation. */

export function Loading({ label = "Reading the blockchain", detail }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <div className={styles.bars} aria-hidden="true">
        <span className={styles.bar} />
        <span className={styles.bar} />
        <span className={styles.bar} />
      </div>
      <p className={styles.title}>{label}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Analysis unavailable" }) {
  const message =
    error?.status === 0
      ? "Cannot reach the Wallerina backend. Start it with: uv run uvicorn backend.main:app --reload"
      : error?.detail || error?.message || "Something went wrong.";

  return (
    <div className={styles.state} role="alert">
      <p className={styles.title}>{title}</p>
      <p className={styles.detail}>{message}</p>
      {onRetry && (
        <button type="button" className={styles.action} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Disconnected() {
  return (
    <div className={styles.state}>
      <p className={styles.title}>No wallet connected</p>
      <p className={styles.detail}>
        Connect a wallet address to read its holdings and run the risk engine
        against them.
      </p>
      <Link href="/" className={styles.action}>
        Connect wallet
      </Link>
    </div>
  );
}

export function Empty({ title, detail }) {
  return (
    <div className={styles.state}>
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
    </div>
  );
}

/** Inline notice for partial-data caveats, e.g. a truncated wallet scan. */
export function Notice({ children }) {
  return <p className={styles.notice}>{children}</p>;
}
