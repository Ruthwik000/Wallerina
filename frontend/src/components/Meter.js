import styles from "./Meter.module.css";

/**
 * Labelled horizontal bar. Used for allocation weights, risk contribution and
 * factor weights so that every proportional readout in the app looks the same.
 */
export default function Meter({ label, value, display, max = 100, secondary, muted = false }) {
  const width = Math.max(0, Math.min((value / max) * 100, 100));

  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <span className={styles.label}>{label}</span>
        <span className={styles.value}>{display ?? `${value.toFixed(1)}%`}</span>
      </div>
      <div className={styles.track}>
        <div
          className={muted ? styles.fillMuted : styles.fill}
          style={{ width: `${width}%` }}
        />
        {secondary != null && (
          <div
            className={styles.marker}
            style={{ left: `${Math.min((secondary / max) * 100, 100)}%` }}
          />
        )}
      </div>
    </div>
  );
}
