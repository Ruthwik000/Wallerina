import styles from "./Stat.module.css";

/**
 * Key figure. `emphasis` lifts the value to the brightest sepia; direction is
 * shown with a caret and a tone shift, never with colour — the palette has no
 * red or green.
 */
export default function Stat({ label, value, delta, deltaLabel, note, emphasis = false, size = "md" }) {
  const direction = delta == null ? null : delta > 0 ? "up" : delta < 0 ? "down" : "flat";

  return (
    <div className={styles.stat}>
      <span className={styles.label}>{label}</span>
      <span
        className={`${styles.value} ${styles[size]} ${emphasis ? styles.emphasis : ""}`}
      >
        {value}
      </span>
      {(delta != null || deltaLabel) && (
        <span className={`${styles.delta} ${direction ? styles[direction] : ""}`}>
          {direction === "up" ? "▲" : direction === "down" ? "▼" : ""}
          {deltaLabel ?? `${Math.abs(delta).toFixed(2)}%`}
        </span>
      )}
      {note && <span className={styles.note}>{note}</span>}
    </div>
  );
}
