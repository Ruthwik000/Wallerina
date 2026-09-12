import styles from "./chart.module.css";

/* Correlation is encoded as sepia density: |rho| drives opacity, so a tightly
   correlated pair reads bright and an uncorrelated pair falls back to black. */
function cellStyle(value) {
  const intensity = Math.min(Math.abs(value), 1);
  return {
    backgroundColor: `rgba(232, 224, 210, ${(0.05 + intensity * 0.8).toFixed(3)})`,
    color: intensity > 0.55 ? "var(--pitch-black)" : "var(--sepia-light)",
  };
}

/**
 * @param {string[]} labels
 * @param {number[][]} matrix  square, same order as labels
 */
export default function Matrix({ labels, matrix }) {
  return (
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
  );
}
