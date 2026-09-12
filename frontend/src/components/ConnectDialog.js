"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { isValidAddress } from "@/lib/api";
import GoalPicker from "./GoalPicker";
import { useWallet } from "./WalletProvider";
import styles from "./ConnectDialog.module.css";

/* A few public wallets, so the product can be tried without pasting an
   address. All are well known and hold real, varied positions. */
const EXAMPLES = [
  { label: "Mixed multi-chain book", address: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045" },
  { label: "Large single-asset book", address: "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe" },
];

/* Two steps: the wallet, then what it is for. The goal sets the rules every
   agent works within, so the analysis does not start without one. */
export default function ConnectDialog({ open, onClose, redirectTo = "/dashboard" }) {
  const { connect, address: currentAddress, goal: currentGoal } = useWallet();
  const router = useRouter();
  const [step, setStep] = useState("wallet");
  const [value, setValue] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setStep("wallet");
      setValue("");
      setGoal("");
      setError(null);
      // Defer so the element exists before focusing.
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const submitWallet = (event) => {
    event.preventDefault();
    if (!isValidAddress(value)) {
      setError("Enter a valid 42-character address starting with 0x");
      return;
    }
    // Reconnecting the same wallet starts from the goal it already has.
    const sameWallet = currentAddress?.toLowerCase() === value.trim().toLowerCase();
    setGoal(sameWallet && currentGoal ? currentGoal : "");
    setStep("goal");
  };

  const submitGoal = (event) => {
    event.preventDefault();
    const chosen = goal.trim();
    if (!chosen) return;
    try {
      connect(value, { goal: chosen });
      onClose();
      router.push(redirectTo);
    } catch (failure) {
      setError(failure.message);
      setStep("wallet");
    }
  };

  const valid = isValidAddress(value);

  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.dialog}>
        {step === "wallet" ? (
          <>
            <header className={styles.header}>
              <p className={styles.eyebrow}>Step 1 of 2 · Wallet</p>
              <h2 id="connect-title" className={styles.title}>
                Enter a wallet address
              </h2>
              <p className={styles.description}>
                Wallerina reads public balances across Ethereum, Base, Arbitrum and
                Polygon. It is read-only and never asks for a key, seed phrase or
                signature.
              </p>
            </header>

            <form className={styles.form} onSubmit={submitWallet}>
              <label className={styles.label} htmlFor="wallet-address">
                Wallet address
              </label>
              <input
                id="wallet-address"
                ref={inputRef}
                className={styles.input}
                type="text"
                inputMode="text"
                autoComplete="off"
                spellCheck="false"
                placeholder="0x0000000000000000000000000000000000000000"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setError(null);
                }}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "wallet-error" : undefined}
              />

              {error ? (
                <p id="wallet-error" className={styles.error} role="alert">
                  {error}
                </p>
              ) : (
                <p className={styles.hint}>42 characters, beginning with 0x.</p>
              )}

              <button type="submit" className={styles.submit} disabled={!valid}>
                Continue
              </button>
            </form>

            <div className={styles.examples}>
              <p className={styles.examplesTitle}>Or try a public wallet</p>
              {EXAMPLES.map((example) => (
                <button
                  key={example.address}
                  type="button"
                  className={styles.example}
                  onClick={() => {
                    setValue(example.address);
                    setError(null);
                    inputRef.current?.focus();
                  }}
                >
                  <span className={styles.exampleLabel}>{example.label}</span>
                  <span className={styles.exampleAddress}>
                    {example.address.slice(0, 10)}···{example.address.slice(-6)}
                  </span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <header className={styles.header}>
              <p className={styles.eyebrow}>Step 2 of 2 · Goal</p>
              <h2 id="connect-title" className={styles.title}>
                What is this wallet for?
              </h2>
              <p className={styles.description}>
                Your goal sets the rules every agent works within: how much may sit
                in volatile assets, the largest loss you would accept and the horizon
                that matters. You can change it later.
              </p>
            </header>

            <form className={styles.form} onSubmit={submitGoal}>
              <GoalPicker initialValue={goal} onChange={setGoal} idPrefix="connect-goal" />
              <button type="submit" className={styles.submit} disabled={!goal.trim()}>
                Start analysis
              </button>
              <button type="button" className={styles.close} onClick={() => setStep("wallet")}>
                Back
              </button>
            </form>
          </>
        )}

        <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
          Cancel
        </button>
      </div>
    </div>
  );
}
