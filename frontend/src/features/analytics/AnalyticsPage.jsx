import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  analyticsOverview,
  analyticsRegions,
  frpTrends,
  hotspotTrends,
  sensorComparison,
} from "../../api/endpoints";
import Panel from "../../components/common/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import {
  SENSOR_COLORS,
  decimal,
  monthLabel,
  number,
  sensorLabel,
} from "../../lib/format";

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border-color)",
  borderRadius: 10,
  fontSize: 12,
  color: "var(--text-primary)",
};

function pivot(rows = [], valueKey) {
  const map = new Map();
  rows.forEach((row) => {
    const entry = map.get(row.bucket) ?? { bucket: row.bucket };
    entry[row.sensor] = row[valueKey];
    map.set(row.bucket, entry);
  });
  return [...map.values()].sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)));
}

export default function AnalyticsPage() {
  const comparison = useApi((options) => sensorComparison(options), []);
  const hotspots = useApi((options) => hotspotTrends({ granularity: "month", ...options }), []);
  const frp = useApi((options) => frpTrends({ granularity: "month", ...options }), []);
  const regions = useApi((options) => analyticsRegions(options), []);
  const overview = useApi((options) => analyticsOverview(options), []);

  const detectionSeries = useMemo(() => pivot(hotspots.data?.series, "detections"), [hotspots.data]);
  const frpSeries = useMemo(() => pivot(frp.data?.series, "mean_frp_mw"), [frp.data]);

  const sensors = comparison.data?.sensors ?? [];
  const agreement = comparison.data?.agreement ?? {};
  const log10 = agreement.log10_frp ?? {};
  const notes = comparison.data?.notes ?? overview.data?.notes ?? [];

  return (
    <div className="space-y-7">
      <div>
        <h2 className="text-2xl font-bold">Analytics</h2>
        <p className="mt-1 text-sm text-(--text-secondary)">
          Sensor-by-sensor statistics and cross-sensor consistency. Sensors are never
          summed into a single hotspot count.
        </p>
      </div>

      {comparison.loading && (
        <Panel><LoadingState label="Loading sensor comparison…" /></Panel>
      )}
      {comparison.error && (
        <Panel><ErrorState error={comparison.error} onRetry={comparison.reload} /></Panel>
      )}

      {!comparison.loading && !comparison.error && (
        <>
          <section className="grid gap-4 lg:grid-cols-2">
            {sensors.map((sensor) => (
              <div
                key={sensor.sensor}
                className="rounded-xl border border-(--border-color) bg-(--surface) p-5"
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">{sensorLabel(sensor.sensor)}</h3>
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: SENSOR_COLORS[sensor.sensor] }}
                  />
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Detections</dt>
                    <dd className="font-semibold">{number(sensor.detections)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Days with detections</dt>
                    <dd className="font-semibold">{number(sensor.distinct_days)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Median FRP</dt>
                    <dd className="font-semibold">{decimal(sensor.median_frp_mw)} MW</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Mean FRP</dt>
                    <dd className="font-semibold">{decimal(sensor.mean_frp_mw)} MW</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Max FRP</dt>
                    <dd className="font-semibold">{decimal(sensor.max_frp_mw)} MW</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-(--text-secondary)">Extent</dt>
                    <dd className="font-mono text-xs">
                      {decimal(sensor.min_lon, 2)}–{decimal(sensor.max_lon, 2)}°E ·{" "}
                      {decimal(sensor.min_lat, 2)}–{decimal(sensor.max_lat, 2)}°N
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </section>

          <Panel
            title="Cross-sensor consistency"
            description={`Matched pairs within the configured radius/time window: ${number(agreement.n_pairs)}. These are cross-sensor consistency metrics, not accuracy against true fire occurrence. Held-out VIIRS reference validation for 2013/2024 is a separate offline step.`}
          >
            {agreement.n_pairs ? (
              <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
                {[
                  ["Matched pairs", number(agreement.n_pairs)],
                  ["log10 FRP MAE", `${decimal(log10.mae, 3)} dex`],
                  ["log10 FRP RMSE", `${decimal(log10.rmse, 3)} dex`],
                  ["Bias (MODIS − VIIRS)", `${log10.bias_modis_minus_viirs > 0 ? "+" : ""}${decimal(log10.bias_modis_minus_viirs, 3)} dex`],
                  ["Pearson r (log10)", decimal(log10.pearson_r, 3)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-(--surface-secondary) p-3">
                    <p className="text-[11px] text-(--text-secondary)">{label}</p>
                    <p className="mt-1 text-lg font-semibold">{value}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="No validation run" description="Run POST /api/v1/validation/run to compute pairs." />
            )}
          </Panel>

          <section className="grid gap-5 xl:grid-cols-2">
            <Panel title="Monthly detections" description="Counts per sensor per month.">
              {detectionSeries.length ? (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={detectionSeries} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                      <XAxis dataKey="bucket" tickFormatter={monthLabel} tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                      <YAxis tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                      <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `${monthLabel(v)} ${String(v).slice(0, 4)}`} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="modis" name="MODIS" fill={SENSOR_COLORS.modis} radius={[3, 3, 0, 0]} />
                      <Bar dataKey="viirs" name="VIIRS" fill={SENSOR_COLORS.viirs} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState title="No hotspot trend data" />
              )}
            </Panel>

            <Panel title="Mean FRP per month" description="Instantaneous radiative power (MW). Never summed into energy.">
              {frpSeries.length ? (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={frpSeries} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                      <XAxis dataKey="bucket" tickFormatter={monthLabel} tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                      <YAxis tick={{ fontSize: 11 }} stroke="var(--text-secondary)" unit=" MW" />
                      <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${decimal(value)} MW`} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Line type="monotone" dataKey="modis" name="MODIS" stroke={SENSOR_COLORS.modis} strokeWidth={2} dot={{ r: 2 }} />
                      <Line type="monotone" dataKey="viirs" name="VIIRS" stroke={SENSOR_COLORS.viirs} strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState title="No FRP trend data" />
              )}
            </Panel>
          </section>

          <Panel
            title="Data-extent regions"
            description="Data-extent boxes (not administrative regions), used as a coarse regional breakdown."
          >
            {regions.error && <ErrorState error={regions.error} onRetry={regions.reload} />}
            {regions.loading && <LoadingState />}
            {regions.data?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-(--text-secondary)">
                    <tr className="border-b border-(--border-color)">
                      <th className="py-2 font-medium">Region</th>
                      <th className="py-2 font-medium">Bounding box</th>
                      <th className="py-2 text-right font-medium">Detections</th>
                      <th className="py-2 text-right font-medium">Mean FRP</th>
                      <th className="py-2 text-right font-medium">Max FRP</th>
                    </tr>
                  </thead>
                  <tbody>
                    {regions.data.map((region) => (
                      <tr key={region.region} className="border-b border-(--border-color)/60 last:border-0">
                        <td className="py-2 font-semibold">{region.region}</td>
                        <td className="py-2 font-mono">
                          {decimal(region.bbox.min_lon, 2)}–{decimal(region.bbox.max_lon, 2)}°E,{" "}
                          {decimal(region.bbox.min_lat, 2)}–{decimal(region.bbox.max_lat, 2)}°N
                        </td>
                        <td className="py-2 text-right">{number(region.detections)}</td>
                        <td className="py-2 text-right">{decimal(region.mean_frp_mw)} MW</td>
                        <td className="py-2 text-right">{decimal(region.max_frp_mw)} MW</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Panel>

          {notes.length > 0 && (
            <Panel title="Method notes from the API">
              <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-(--text-secondary)">
                {[...new Set(notes)].map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
