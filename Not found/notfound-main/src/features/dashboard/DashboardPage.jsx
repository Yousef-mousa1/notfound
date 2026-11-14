import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Flame,
  Globe2,
  Satellite,
  TrendingUp,
} from "lucide-react";
import {
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
  analyticsRegions,
  dashboardAnomalies,
  dashboardOverview,
  dashboardTrends,
} from "../../api/endpoints";
import Badge from "../../components/common/Badge";
import Panel from "../../components/common/Panel";
import StatCard from "../../components/common/StatCard";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import {
  SENSOR_COLORS,
  dateOnly,
  dateTime,
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

function pivotByBucket(rows = []) {
  const map = new Map();
  rows.forEach((row) => {
    const key = row.bucket;
    const entry = map.get(key) ?? { bucket: key };
    entry[row.sensor] = row.detections;
    entry[`${row.sensor}_frp`] = row.mean_frp_mw;
    map.set(key, entry);
  });
  return [...map.values()].sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)));
}

function SensorCard({ sensor }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-(--border-color) bg-(--surface-secondary) p-4">
      <div className="rounded-lg bg-(--surface) p-3">
        <Satellite size={21} style={{ color: SENSOR_COLORS[sensor.sensor] }} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold">{sensorLabel(sensor.sensor)}</p>
          <Badge variant={sensor.sensor}>{number(sensor.detections)} detections</Badge>
        </div>
        <p className="mt-1 text-xs text-(--text-secondary)">
          {number(sensor.distinct_days)} days with detections · median FRP{" "}
          {decimal(sensor.median_frp_mw)} MW · max {decimal(sensor.max_frp_mw)} MW
        </p>
        <p className="mt-0.5 text-[11px] text-(--text-secondary)">
          {dateOnly(sensor.first_detection_utc)} → {dateOnly(sensor.last_detection_utc)}
        </p>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const overview = useApi((options) => dashboardOverview(options), []);
  const trends = useApi((options) => dashboardTrends(options), []);
  const anomalies = useApi((options) => dashboardAnomalies(options), []);
  const regions = useApi((options) => analyticsRegions(options), []);

  if (overview.loading) {
    return (
      <Panel title="Overview">
        <LoadingState />
      </Panel>
    );
  }

  if (overview.error) {
    return (
      <Panel title="Overview">
        <ErrorState error={overview.error} onRetry={overview.reload} />
      </Panel>
    );
  }

  const data = overview.data ?? {};
  const observations = data.observations ?? {};
  const monthly = pivotByBucket(trends.data?.monthly);
  const daily = pivotByBucket(trends.data?.daily).slice(-60);
  const topCells = anomalies.data?.top_cells?.slice(0, 6) ?? [];
  const severity = anomalies.data?.statistics?.per_severity ?? [];

  return (
    <div className="space-y-7">
      <section className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Overview</h2>
          <p className="mt-1 text-sm text-(--text-secondary)">
            Live harmonized fire activity from the PyroScope API.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-(--border-color) bg-(--surface) px-3 py-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span className="text-xs text-(--text-secondary)">
            API connected · {dateOnly(observations.first_detection_utc)} →{" "}
            {dateOnly(observations.last_detection_utc)}
          </span>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Fire detections"
          value={number(observations.detections)}
          description="MODIS + VIIRS observations in the store"
          footnote={`${number(observations.distinct_days)} distinct days · median FRP ${decimal(observations.median_frp_mw)} MW`}
          icon={Flame}
        />
        <StatCard
          title="Harmonized cell-days"
          value={number(data.harmonization?.count)}
          description="25 km cells aggregated per day"
          footnote={
            data.harmonization?.available
              ? `Run ${data.harmonization.run_id}`
              : "No harmonization run stored yet"
          }
          icon={Activity}
          accent="blue"
        />
        <StatCard
          title="Data-extent regions"
          value={number(regions.data?.length)}
          description="Data-extent boxes, not administrative regions"
          footnote={`Extent ${decimal(observations.min_lon, 2)}–${decimal(observations.max_lon, 2)}°E, ${decimal(observations.min_lat, 2)}–${decimal(observations.max_lat, 2)}°N`}
          icon={Globe2}
          accent="green"
        />
        <StatCard
          title="Flagged anomalies"
          value={number(data.anomalies?.count)}
          description="Statistical outliers on daily per-cell counts"
          footnote={`${number(anomalies.data?.statistics?.overall?.cells)} cells · ${number(anomalies.data?.statistics?.overall?.days)} days`}
          icon={AlertTriangle}
          accent="red"
        />
      </section>

      <section className="grid gap-5 xl:grid-cols-3">
        <Panel
          title="Monthly fire activity"
          description="Detections per sensor per month. Sensors are reported separately and never summed into one hotspot count."
          className="xl:col-span-2"
          bodyClassName="pt-3"
        >
          {trends.loading && <LoadingState />}
          {trends.error && <ErrorState error={trends.error} onRetry={trends.reload} />}
          {!trends.loading && !trends.error && monthly.length === 0 && (
            <EmptyState title="No trend data" description="Import a source file to populate this chart." />
          )}
          {monthly.length > 0 && (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={monthly} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                  <XAxis dataKey="bucket" tickFormatter={monthLabel} tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                  <YAxis tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                  <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `${monthLabel(v)} ${String(v).slice(0, 4)}`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="modis" name="MODIS" stroke={SENSOR_COLORS.modis} strokeWidth={2} dot={{ r: 2 }} connectNulls />
                  <Line type="monotone" dataKey="viirs" name="VIIRS" stroke={SENSOR_COLORS.viirs} strokeWidth={2} dot={{ r: 2 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Anomaly severity" description="Bands from the latest anomaly run.">
          {anomalies.loading && <LoadingState />}
          {anomalies.error && <ErrorState error={anomalies.error} onRetry={anomalies.reload} />}
          {!anomalies.loading && !anomalies.error && severity.length === 0 && (
            <EmptyState title="No anomaly run" description="Run POST /api/v1/anomalies/detect first." />
          )}
          {severity.length > 0 && (
            <ul className="space-y-3">
              {severity.map((band) => (
                <li key={band.severity} className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Badge variant={band.severity}>{band.severity}</Badge>
                    <span className="text-xs text-(--text-secondary)">
                      {number(band.cells)} cells
                    </span>
                  </div>
                  <span className="text-sm font-semibold">{number(band.anomalies)}</span>
                </li>
              ))}
              <li className="border-t border-(--border-color) pt-3 text-[11px] leading-5 text-(--text-secondary)">
                Max robust z-score {decimal(anomalies.data?.statistics?.overall?.max_robust_z, 1)}.
                An anomaly is a statistical deviation from the same cell/sensor series, not proof of an unusual fire.
              </li>
            </ul>
          )}
        </Panel>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <Panel title="Recent activity (last 60 days in the series)" description="Daily detections per sensor.">
          {daily.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={daily} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                  <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5)} tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                  <YAxis tick={{ fontSize: 11 }} stroke="var(--text-secondary)" />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="modis" name="MODIS" stroke={SENSOR_COLORS.modis} strokeWidth={2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="viirs" name="VIIRS" stroke={SENSOR_COLORS.viirs} strokeWidth={2} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No daily series" />
          )}
        </Panel>

        <Panel
          title="Top anomaly cells"
          description="Cells with the most flagged days in the latest run."
          action={
            <Link to="/map" className="flex items-center gap-1 text-xs font-medium text-orange-500 hover:text-orange-400">
              Explore map <ArrowUpRight size={15} />
            </Link>
          }
        >
          {topCells.length === 0 ? (
            <EmptyState title="No anomaly cells" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-(--text-secondary)">
                  <tr className="border-b border-(--border-color)">
                    <th className="py-2 font-medium">Cell</th>
                    <th className="py-2 font-medium">Sensor</th>
                    <th className="py-2 text-right font-medium">Anomalies</th>
                    <th className="py-2 text-right font-medium">Extreme</th>
                    <th className="py-2 text-right font-medium">Max z</th>
                  </tr>
                </thead>
                <tbody>
                  {topCells.map((cell) => (
                    <tr key={`${cell.cell_id}-${cell.sensor}`} className="border-b border-(--border-color)/60 last:border-0">
                      <td className="py-2 font-mono">{cell.cell_id}</td>
                      <td className="py-2"><Badge variant={cell.sensor}>{sensorLabel(cell.sensor)}</Badge></td>
                      <td className="py-2 text-right">{number(cell.anomalies)}</td>
                      <td className="py-2 text-right">{number(cell.extreme)}</td>
                      <td className="py-2 text-right">{decimal(cell.max_robust_z, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </section>

      <Panel title="Data sources" description="Imported source files and their per-sensor statistics.">
        <div className="grid gap-3 lg:grid-cols-2">
          {(data.per_sensor ?? []).map((sensor) => (
            <SensorCard key={sensor.sensor} sensor={sensor} />
          ))}
        </div>
        <p className="mt-4 flex items-start gap-2 text-[11px] leading-5 text-(--text-secondary)">
          <TrendingUp size={14} className="mt-0.5 shrink-0" />
          {data.notes?.join(" ") ??
            "Source files contain detections only: a missing row is not proof of no fire."}{" "}
          Last aggregation {dateTime(data.harmonization?.created_at)}.
        </p>
      </Panel>
    </div>
  );
}
