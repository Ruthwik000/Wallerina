"use client";

import { useEffect, useState } from "react";
import GoalPicker from "./GoalPicker";
import { useWallet } from "./WalletProvider";
import styles from "./ConnectDialog.module.css";

/** Change the connected wallet's goal. Shares the connect dialog's surface. */
export default function GoalDialog({ open, onClose }) {
  const { goal, setGoal } = useWallet();
  const [value, setValue] = useState(goal ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setValue(goal ?? "");
    // Only reset when the dialog opens, not while the user is choosing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const submit = async (event) => {
    event.preventDefault();
    const chosen = value.trim();
    if (!chosen) return;
    setSaving(true);
    await setGoal(chosen);
    setSaving(false);
    onClose();
  };

  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="goal-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.dialog}>
        <header className={styles.header}>
          <p className={styles.eyebrow}>Goal</p>
          <h2 id="goal-title" className={styles.title}>
            What is this wallet for?
          </h2>
          <p className={styles.description}>
            The goal sets the rules every agent works within: how much may sit in
            volatile assets, the largest loss you would accept and the horizon that
            matters. Recommendations re-run when it changes.
          </p>
        </header>

        <form className={styles.form} onSubmit={submit}>
          <GoalPicker initialValue={goal ?? ""} onChange={setValue} idPrefix="change-goal" />
          <button type="submit" className={styles.submit} disabled={!value.trim() || saving}>
            {saving ? "Saving" : "Save goal"}
          </button>
        </form>

        <button type="button" className={styles.close} onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
