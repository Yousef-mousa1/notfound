// Small formatting helpers shared by every page.

export const number = (value, options = {}) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return Number(value).toLocaleString("en-US", options);
};

export const decimal = (value, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return Number(value).toFixed(digits);
};

export const dateTime = (iso) => {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().replace("T", " ").slice(0, 16) + " UTC";
};

export const dateOnly = (iso) => (iso ? String(iso).slice(0, 10) : "—");

export const monthLabel = (bucket) => {
  if (!bucket) return "—";
  const date = new Date(`${String(bucket).slice(0, 10)}T00:00:00Z`);
  return date.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
};

export const dayLabel = (bucket) => {
  if (!bucket) return "—";
  const date = new Date(`${String(bucket).slice(0, 10)}T00:00:00Z`);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
};

export const sensorLabel = (sensor) =>
  ({ modis: "MODIS", viirs: "VIIRS" }[sensor] ?? String(sensor ?? "").toUpperCase());

export const SENSOR_COLORS = {
  modis: "#f97316",
  viirs: "#eab308",
};

export const percentChange = (value, baseline) => {
  if (!baseline || value === null || value === undefined) return null;
  return ((value - baseline) / baseline) * 100;
};
