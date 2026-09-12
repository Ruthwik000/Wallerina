import styles from "./chart.module.css";

const SIZE = 220;
const RADIUS = 88;
const THICKNESS = 26;

/* Opacity ramp keeps every slice on the same sepia, differentiated by weight
   rather than by hue — the palette allows no second colour. */
function sliceOpacity(index, total) {
  const top = 0.92;
  const bottom = 0.2;
  return top - ((top - bottom) * index) / Math.max(total - 1, 1);
}

function arc(startAngle, endAngle) {
  const center = SIZE / 2;
  const outer = RADIUS;
  const inner = RADIUS - THICKNESS;
  const large = endAngle - startAngle > Math.PI ? 1 : 0;

  const point = (angle, radius) => [
    center + radius * Math.cos(angle - Math.PI / 2),
    center + radius * Math.sin(angle - Math.PI / 2),
  ];

  const [x1, y1] = point(startAngle, outer);
  const [x2, y2] = point(endAngle, outer);
  const [x3, y3] = point(endAngle, inner);
  const [x4, y4] = point(startAngle, inner);

  return [
    `M${x1.toFixed(2)},${y1.toFixed(2)}`,
    `A${outer},${outer} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)}`,
    `L${x3.toFixed(2)},${y3.toFixed(2)}`,
    `A${inner},${inner} 0 ${large} 0 ${x4.toFixed(2)},${y4.toFixed(2)}`,
    "Z",
  ].join(" ");
}

/**
 * Allocation ring.
 *
 * @param {{symbol: string, weight: number}[]} segments  weights in percent
 */
export default function Donut({ segments, caption, captionLabel }) {
  let cursor = 0;

  return (
    <div className={styles.donutWrap}>
      <svg
        className={styles.donut}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label="Asset allocation"
      >
        {segments.map((segment, index) => {
          const start = cursor;
          const end = cursor + (segment.weight / 100) * Math.PI * 2;
          cursor = end;
          return (
            <path
              key={segment.symbol}
              d={arc(start, Math.max(end - 0.012, start))}
              fill="var(--sepia-light)"
              fillOpacity={sliceOpacity(index, segments.length)}
            />
          );
        })}
        {caption && (
          <>
            <text className={styles.donutValue} x={SIZE / 2} y={SIZE / 2 - 2}>
              {caption}
            </text>
            <text className={styles.donutLabel} x={SIZE / 2} y={SIZE / 2 + 16}>
              {captionLabel}
            </text>
          </>
        )}
      </svg>

      <ul className={styles.donutLegend}>
        {segments.map((segment, index) => (
          <li key={segment.symbol} className={styles.donutLegendRow}>
            <span
              className={styles.swatch}
              style={{ opacity: sliceOpacity(index, segments.length) }}
            />
            <span className={styles.donutSymbol}>{segment.symbol}</span>
            <span className={styles.donutWeight}>{segment.weight.toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
