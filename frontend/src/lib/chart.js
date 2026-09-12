/* Geometry helpers shared by the SVG chart components.

   All charts draw into a fixed viewBox and scale with `preserveAspectRatio`,
   so they stay resolution-independent without a measurement pass. */

export function extent(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (min === max) {
    return [min - 1, max + 1];
  }
  return [min, max];
}

export function padExtent([min, max], ratio = 0.08) {
  const span = (max - min) * ratio;
  return [min - span, max + span];
}

/* Maps a value from a domain onto a pixel range. */
export function scale(value, [d0, d1], [r0, r1]) {
  if (d1 === d0) return (r0 + r1) / 2;
  return r0 + ((value - d0) / (d1 - d0)) * (r1 - r0);
}

export function linePath(points) {
  return points
    .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
}

export function areaPath(top, bottom) {
  return `${linePath(top)} L${bottom
    .slice()
    .reverse()
    .map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" L")} Z`;
}

/* Evenly spaced tick values across a domain, inclusive of both ends. */
export function ticks([min, max], count = 4) {
  return Array.from({ length: count + 1 }, (_, index) =>
    min + ((max - min) / count) * index
  );
}
