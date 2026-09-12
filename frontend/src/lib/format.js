/* Display formatters. Every number in the UI goes through one of these so that
   grouping, precision and sign conventions stay identical across pages. */

export function usd(value, { compact = false, decimals = 2 } = {}) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : decimals,
    minimumFractionDigits: compact ? 0 : decimals,
  }).format(value);
}

/* The API reports shares as 0-1 fractions; the UI shows percentages. Keeping
   the conversion in one place avoids scattered `* 100` arithmetic. */
export function ratio(value, { decimals = 1, sign = false } = {}) {
  if (value == null || Number.isNaN(value)) return "—";
  return percent(value * 100, { decimals, sign });
}

export function percent(value, { decimals = 1, sign = false } = {}) {
  if (value == null || Number.isNaN(value)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  const prefix = sign && value > 0 ? "+" : "";
  return `${prefix}${formatted}%`;
}

export function quantity(value, symbol) {
  if (value == null) return "—";
  const decimals = value >= 1000 ? 2 : value >= 1 ? 4 : 6;
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: decimals,
  }).format(value);
  return symbol ? `${formatted} ${symbol}` : formatted;
}

export function shortAddress(address, lead = 6, tail = 4) {
  if (!address) return "—";
  return `${address.slice(0, lead)}···${address.slice(-tail)}`;
}

export function dateLabel(iso) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function timeLabel(iso) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
