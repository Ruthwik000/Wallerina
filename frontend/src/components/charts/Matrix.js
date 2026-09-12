import styles from "./chart.module.css";

/* Correlation is polarity, not magnitude: -0.8 and +0.8 are opposite facts,
   and an opacity ramp renders them identically. Two hues either side of a warm
   neutral, with equal steps per arm. */
const NEGATIVE = [
  "var(--corr-neg-1)",
  "var(--corr-neg-2)",
  "var(--corr-neg-3)",
  "var(--corr-neg-4)",
];
const POSITIVE = [
  "var(--corr-pos-1)",
  "var(--corr-pos-2)",
  "var(--corr-pos-3)",
  "var(--corr-pos-4)",
];

function cellStyle(value) {
  const magnitude = Math.min(Math.abs(value), 1);

  if (magnitude < 0.2) {
    return { backgroundColor: "var(--corr-mid)", color: "var(--sepia-grey)" };
  }

  // Four equal steps per arm across |r| 0.2 - 1.0.
  const step = Math.min(Math.floor((magnitude - 0.2) / 0.2), 3);
  const arm = value < 0 ? NEGATIVE : POSITIVE;

  return {
    backgroundColor: arm[step],
    // The top step is light enough that dark ink reads better on it.
    color: step === 3 ? "var(--pitch-black)" : "var(--sepia-light)",
  };
}

/**
 * @param {string[]} labels
 * @param {number[][]} matrix  square, same order as labels
 */
export default function Matrix({ labels, matrix }) {
  return (
    <>
      <table className={styles.matrix}>
        <thead>
          <tr>
            <th className={styles.rowHead} scope="col" />
            {labels.map((label) => (
              <th key={label} scope="col">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, rowIndex) => (
            <tr key={labels[rowIndex]}>
              <th className={styles.rowHead} scope="row">
                {labels[rowIndex]}
              </th>
              {row.map((value, columnIndex) => (
                <td
                  key={labels[columnIndex]}
                  className={styles.matrixCell}
                  style={cellStyle(value)}
                >
                  {value.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className={styles.scale}>
        <span className={styles.scaleLabel}>Inverse −1</span>
        <span className={styles.scaleRamp}>
          {[...NEGATIVE].reverse().map((color) => (
            <span key={color} className={styles.scaleStep} style={{ background: color }} />
          ))}
          <span className={styles.scaleStep} style={{ background: "var(--corr-mid)" }} />
          {POSITIVE.map((color) => (
            <span key={color} className={styles.scaleStep} style={{ background: color }} />
          ))}
        </span>
        <span className={styles.scaleLabel}>+1 Moves together</span>
      </div>
    </>
  );
}
