// Endpoint wrappers. Each function returns the API payload's `data` object
// and never invents values: optional panels may report `available: false`.
//
// Callers pass query parameters together with an optional `signal` (from
// useApi). `signal` is routed to fetch; every other field becomes a query
// parameter.

import { get, post, postBlob } from "./client";

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

// --------------------------------------------------------------- dashboard
export const dashboardOverview = query(`${PREFIX}/dashboard/overview`);
export const dashboardTrends = query(`${PREFIX}/dashboard/trends`);
export const dashboardCalendar = query(`${PREFIX}/dashboard/calendar`);
export const dashboardEstimatesCalendar = query(`${PREFIX}/dashboard/estimates-calendar`);
export const dashboardAnomalies = query(`${PREFIX}/dashboard/anomalies`);
export const dashboardMap = query(`${PREFIX}/dashboard/map`);

// --------------------------------------------------------------- analytics
export const analyticsOverview = query(`${PREFIX}/analytics/overview`);
export const hotspotTrends = query(`${PREFIX}/analytics/hotspot-trends`);
export const frpTrends = query(`${PREFIX}/analytics/frp-trends`);
export const monthlyAnalytics = query(`${PREFIX}/analytics/monthly`);
export const analyticsRegions = query(`${PREFIX}/analytics/regions`);
export const sensorComparison = query(`${PREFIX}/analytics/sensor-comparison`);
export const observationStatistics = query(`${PREFIX}/observations/statistics`);
export const observationCountries = query(`${PREFIX}/observations/countries`);
// ----------------------------------------------------------------- exports
// Stateless export: the create POST returns the file bytes directly (a ZIP
// containing the data + metadata). We hand them to the browser so pressing
// Export downloads immediately. There is no record and no history.
export const createExport = (kind, body = {}) =>
  postBlob(`${PREFIX}/exports/${kind}`, body).then((result) => {
    const url = URL.createObjectURL(result.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.fileName || `${kind}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoke only after the browser has started the download.
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return { fileName: link.download, ...result };
  });
