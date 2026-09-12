import styles from "./Table.module.css";

/**
 * Data table.
 *
 * @param {{key: string, header: string, align?: "left"|"right", width?: string}[]} columns
 * @param {object[]} rows
 * @param {(row: object) => React.ReactNode} renderCell  receives (row, column)
 */
export default function Table({ columns, rows, renderCell, rowKey, onRowSelect, selectedKey }) {
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={{ textAlign: column.align ?? "left", width: column.width }}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const selected = selectedKey === key;
            return (
              <tr
                key={key}
                className={`${onRowSelect ? styles.selectable : ""} ${selected ? styles.selected : ""}`}
                onClick={onRowSelect ? () => onRowSelect(row) : undefined}
                tabIndex={onRowSelect ? 0 : undefined}
                onKeyDown={
                  onRowSelect
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowSelect(row);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((column) => (
                  <td key={column.key} style={{ textAlign: column.align ?? "left" }}>
                    {renderCell(row, column)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
