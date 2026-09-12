"use client";

import styles from "./Toggle.module.css";

/**
 * Square switch. A pill switch is disallowed by the spec, so state is shown by
 * a filled square sliding inside a rectangular track.
 */
export default function Toggle({ checked, onChange, label, description, id }) {
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <label className={styles.label} htmlFor={id}>
          {label}
        </label>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        className={`${styles.track} ${checked ? styles.on : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.knob} />
      </button>
    </div>
  );
}
