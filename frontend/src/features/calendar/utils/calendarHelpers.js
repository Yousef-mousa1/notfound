export const monthNames = [
  "Jan", "Feb", "Mar", "Apr",
  "May", "Jun", "Jul", "Aug",
  "Sep", "Oct", "Nov", "Dec",
];

// Colour levels for a monthly value relative to the maximum in the view.
export function getActivityLevel(value, maxValue) {
  if (value === null || value === undefined) return "no-data";
  if (value === 0) return "zero";

  const ratio = maxValue > 0 ? value / maxValue : 0;

  if (ratio <= 0.25) return "low";
  if (ratio <= 0.5) return "medium";
  if (ratio <= 0.75) return "high";

  return "very-high";
}

// Accessible sequential ramp (yellow → orange → red) for counts and FRP.
export function getActivityColor(level) {
  const colors = {
    "no-data": "bg-(--surface-secondary) opacity-40",
    zero: "bg-slate-100 dark:bg-slate-800",
    low: "bg-amber-200 dark:bg-amber-950",
    medium: "bg-orange-400 dark:bg-orange-800",
    high: "bg-orange-600 dark:bg-orange-600",
    "very-high": "bg-red-600 dark:bg-red-500",
  };

  return colors[level] ?? colors["no-data"];
}

export function getAnomalyColor(value) {
  if (value === null || value === undefined) return "bg-(--surface-secondary) opacity-40";
  if (value <= -25) return "bg-blue-600 dark:bg-blue-700";
  if (value < 0) return "bg-blue-300 dark:bg-blue-900";
  if (value < 25) return "bg-amber-300 dark:bg-amber-800";
  if (value < 50) return "bg-orange-500";
  return "bg-red-600";
}

// Merge per-sensor monthly rows into one record per (year, month).
export function buildMonthlySeries(rows = []) {
  const map = new Map();

  rows.forEach((row) => {
    const date = new Date(`${String(row.bucket).slice(0, 10)}T00:00:00Z`);
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth() + 1;
    const key = `${year}-${month}`;
    const entry = map.get(key) ?? {
      key,
      year,
      month,
      modis: null,
      viirs: null,
      modis_mean_frp: null,
      viirs_mean_frp: null,
      modis_max_frp: null,
      viirs_max_frp: null,
    };

    entry[row.sensor] = row.detections;
    entry[`${row.sensor}_mean_frp`] = row.mean_frp_mw;
    entry[`${row.sensor}_max_frp`] = row.max_frp_mw;
    map.set(key, entry);
  });

  return [...map.values()]
    .map((entry) => {
      const sensors = [entry.modis, entry.viirs].filter((v) => v !== null);
      const frps = [entry.modis_mean_frp, entry.viirs_mean_frp].filter((v) => v !== null);
      return {
        ...entry,
        total: sensors.reduce((sum, v) => sum + v, 0),
        mean_frp: frps.length ? frps.reduce((s, v) => s + v, 0) / frps.length : null,
        max_frp: Math.max(entry.modis_max_frp ?? 0, entry.viirs_max_frp ?? 0) || null,
      };
    })
    .sort((a, b) => a.year - b.year || a.month - b.month);
}

// Historical median per calendar month across the *other* years present in
// the data. With a single year there is no baseline, so the value is null
// (the UI must say so instead of inventing a number).
export function addHistoricalBaseline(series) {
  const years = [...new Set(series.map((item) => item.year))];
  const singleYear = years.length < 2;

  return series.map((item) => {
    const others = series.filter(
      (other) => other.month === item.month && other.year !== item.year
    );

    const baseline =
      others.length > 0
        ? median(others.map((other) => other.total))
        : null;

    return {
      ...item,
      historical_median: baseline,
      anomaly_percentage:
        baseline && baseline > 0
          ? ((item.total - baseline) / baseline) * 100
          : null,
      single_year_sample: singleYear,
    };
  });
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

export function isoDate(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
