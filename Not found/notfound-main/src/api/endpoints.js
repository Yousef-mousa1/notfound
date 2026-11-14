// Endpoint wrappers. Each function returns the API payload's `data` object
// and never invents values: optional panels may report `available: false`.
//
// Callers pass query parameters together with an optional `signal` (from
// useApi). `signal` is routed to fetch; every other field becomes a query
// parameter.

import { get, post } from "./client";

const PREFIX = "/api/v1";

const unwrap = (promise) => promise.then((payload) => payload?.data ?? null);

const splitSignal = (input = {}) => {
  const { signal, ...params } = input;
  return { signal, params };
};

const query = (path) => (input) => {
  const { signal, params } = splitSignal(input);
  return unwrap(get(path, { params, signal }));
};

// ------------------------------------------------------------------ health
export const health = () => unwrap(get("/health"));

// --------------------------------------------------------------- dashboard
export const dashboardOverview = query(`${PREFIX}/dashboard/overview`);
export const dashboardTrends = query(`${PREFIX}/dashboard/trends`);
export const dashboardCalendar = query(`${PREFIX}/dashboard/calendar`);
export const dashboardAnomalies = query(`${PREFIX}/dashboard/anomalies`);
export const dashboardMap = query(`${PREFIX}/dashboard/map`);
export const dashboardActivityIndex = query(`${PREFIX}/dashboard/activity-index`);

// --------------------------------------------------------------- analytics
// -------------------------------------------------------- harmonization
export const harmonizationCells = query(`${PREFIX}/harmonization/cells`);

export const analyticsOverview = query(`${PREFIX}/analytics/overview`);
export const hotspotTrends = query(`${PREFIX}/analytics/hotspot-trends`);
export const frpTrends = query(`${PREFIX}/analytics/frp-trends`);
export const monthlyAnalytics = query(`${PREFIX}/analytics/monthly`);
export const analyticsRegions = query(`${PREFIX}/analytics/regions`);
export const sensorComparison = query(`${PREFIX}/analytics/sensor-comparison`);
export const observationStatistics = query(`${PREFIX}/observations/statistics`);

// ----------------------------------------------------------------- exports
export const exportHistory = query(`${PREFIX}/exports/history`);

export const createExport = (kind, body = {}) =>
  unwrap(post(`${PREFIX}/exports/${kind}`, body));

export const downloadUrl = (record, fileName) => {
  if (!record?.export_id) return null;
  const params = new URLSearchParams({ download: "true" });
  if (fileName) params.set("file", fileName);
  return `${PREFIX}/exports/${record.export_id}?${params.toString()}`;
};
