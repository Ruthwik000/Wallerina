import { extent, scale } from "@/lib/chart";
import styles from "./chart.module.css";

const WIDTH = 760;
const HEIGHT = 220;
const PAD = { top: 12, right: 0, bottom: 26, left: 0 };

/**
 * Distribution of simulated terminal values. Bins below `threshold` are drawn
 * muted so the loss region reads at a glance.
 *
 * @param {{from: number, to: number, count: number}[]} bins
 */
export default function Histogram({ bins, threshold, markers = [], formatValue }) {
  const maxCount = extent(bins.map((bin) => bin.count))[1];
  const x0 = PAD.left;
  const x1 = WIDTH - PAD.right;
  const y0 = HEIGHT - PAD.bottom;
  const y1 = PAD.top;

  const valueDomain = [bins[0].from, bins[bins.length - 1].to];
  const slot = (x1 - x0) / bins.length;

  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Simulated portfolio distribution"
    >
      {bins.map((bin, index) => {
        const height = scale(bin.count, [0, maxCount], [0, y0 - y1]);
        const isLoss = threshold != null && bin.to <= threshold;
        return (
          <rect
            key={bin.from}
            className={isLoss ? styles.barLoss : styles.barGain}
            x={x0 + slot * index + 1}
            y={y0 - height}
            width={Math.max(slot - 2, 1)}
            height={height}
          />
        );
      })}

      {markers.map((marker) => {
        const x = scale(marker.value, valueDomain, [x0, x1]);
        return (
          <g key={marker.label}>
            <line className={styles.marker} x1={x} x2={x} y1={y1} y2={y0} />
            <text className={`${styles.tick} ${styles.tickMid}`} x={x} y={y1 - 2}>
              {marker.label}
            </text>
          </g>
        );
      })}

      <line className={styles.axis} x1={x0} x2={x1} y1={y0} y2={y0} />

      {[0, 0.5, 1].map((fraction, position) => {
        const value = valueDomain[0] + (valueDomain[1] - valueDomain[0]) * fraction;
        return (
          <text
            key={fraction}
            className={`${styles.tick} ${position === 1 ? styles.tickMid : position === 2 ? styles.tickEnd : ""}`}
            x={x0 + (x1 - x0) * fraction}
            y={HEIGHT - 6}
          >
            {formatValue(value)}
          </text>
        );
      })}
    </svg>
  );
}
