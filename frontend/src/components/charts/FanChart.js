import { areaPath, extent, linePath, padExtent, scale, ticks } from "@/lib/chart";
import styles from "./chart.module.css";

const WIDTH = 760;
const HEIGHT = 300;
const PAD = { top: 12, right: 62, bottom: 26, left: 0 };

/**
 * Monte Carlo percentile fan: 5–95 outer band, 25–75 inner band, median line.
 *
 * @param {{t: string, p5: number, p25: number, median: number, p75: number, p95: number}[]} paths
 */
export default function FanChart({ paths, formatValue = (value) => value.toFixed(0) }) {
  const domain = padExtent(
    extent(paths.flatMap((point) => [point.p5, point.p95]))
  );
  const x0 = PAD.left;
  const x1 = WIDTH - PAD.right;
  const y0 = HEIGHT - PAD.bottom;
  const y1 = PAD.top;

  const project = (key) =>
    paths.map((point, index) => [
      scale(index, [0, paths.length - 1], [x0, x1]),
      scale(point[key], domain, [y0, y1]),
    ]);

  const p5 = project("p5");
  const p25 = project("p25");
  const median = project("median");
  const p75 = project("p75");
  const p95 = project("p95");

  const yTicks = ticks(domain, 3);

  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Monte Carlo percentile fan chart"
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

      <path className={styles.bandOuter} d={areaPath(p95, p5)} />
      <path className={styles.bandInner} d={areaPath(p75, p25)} />
      <path className={styles.medianLine} d={linePath(median)} />

      <line className={styles.axis} x1={x0} x2={x1} y1={y0} y2={y0} />

      {[0, Math.floor(paths.length / 2), paths.length - 1].map((index, position) => (
        <text
          key={index}
          className={`${styles.tick} ${position === 0 ? "" : styles.tickMid}`}
          x={scale(index, [0, paths.length - 1], [x0, x1])}
          y={HEIGHT - 6}
        >
          {`Day ${index}`}
        </text>
      ))}
    </svg>
  );
}
