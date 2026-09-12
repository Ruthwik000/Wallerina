import { areaPath, extent, linePath, padExtent, scale, ticks } from "@/lib/chart";
import styles from "./chart.module.css";

const WIDTH = 760;
const HEIGHT = 240;
const PAD = { top: 12, right: 56, bottom: 24, left: 0 };

/**
 * Single-series line chart with an optional filled area.
 *
 * @param {{t: string, v: number}[]} series
 * @param {(value: number) => string} formatValue  y-axis tick label
 * @param {(iso: string) => string} formatDate     x-axis tick label
 */
export default function LineChart({
  series,
  formatValue = (value) => value.toFixed(0),
  formatDate = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short" }),
  area = true,
  height = HEIGHT,
}) {
  const values = series.map((point) => point.v);
  const domain = padExtent(extent(values));
  const x0 = PAD.left;
  const x1 = WIDTH - PAD.right;
  const y0 = height - PAD.bottom;
  const y1 = PAD.top;

  const points = series.map((point, index) => [
    scale(index, [0, series.length - 1], [x0, x1]),
    scale(point.v, domain, [y0, y1]),
  ]);

  const yTicks = ticks(domain, 3);
  const xTickIndexes = [0, Math.floor(series.length / 3), Math.floor((series.length * 2) / 3), series.length - 1];

  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label="Line chart"
    >
      {yTicks.map((tick) => {
        const y = scale(tick, domain, [y0, y1]);
        return (
          <g key={tick}>
            <line className={styles.grid} x1={x0} x2={x1} y1={y} y2={y} />
            <text className={styles.tick} x={x1 + 10} y={y + 3}>
              {formatValue(tick)}
            </text>
          </g>
        );
      })}

      {area && (
        <path
          className={styles.area}
          d={areaPath(points, [
            [x0, y0],
            [x1, y0],
          ])}
        />
      )}
      <path className={styles.line} d={linePath(points)} />

      <line className={styles.axis} x1={x0} x2={x1} y1={y0} y2={y0} />

      {xTickIndexes.map((index, position) => (
        <text
          key={index}
          className={`${styles.tick} ${position === 0 ? "" : styles.tickMid}`}
          x={scale(index, [0, series.length - 1], [x0, x1])}
          y={height - 6}
        >
          {formatDate(series[index].t)}
        </text>
      ))}
    </svg>
  );
}
