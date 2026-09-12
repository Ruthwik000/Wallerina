import styles from "./Classification.module.css";

/* Classification is the one label in the interface where colour does real
   work: "unknown" counts as volatile exposure, and that distinction is easy
   to miss in a table of monochrome text. The word is always present, so the
   meaning never rests on colour alone. */
const CLASS_NAMES = {
  stablecoin: styles.stablecoin,
  volatile: styles.volatile,
  unknown: styles.unknown,
};

export default function Classification({ value }) {
  return (
    <span className={`${styles.label} ${CLASS_NAMES[value] ?? ""}`}>
      <span className={styles.mark} aria-hidden="true" />
      {value}
    </span>
  );
}
