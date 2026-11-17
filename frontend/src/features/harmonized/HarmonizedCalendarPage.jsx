import { useMemo, useState } from "react";

import { dashboardEstimatesCalendar } from "../../api/endpoints";
import Badge from "../../components/common/Badge";
import Panel from "../../components/common/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import { number } from "../../lib/format";
import { monthNames } from "../calendar/utils/calendarHelpers";

const SCALES = [
  { key: "viirs_harmonized", label: "VIIRS harmonized (coverage corrected)" },
  { key: "modis_raw", label: "MODIS raw (uncorrected)" },
];

const levelClass = (ratio) => {
  if (!Number.isFinite(ratio) || ratio <= 0) return "bg-slate-100 dark:bg-slate-800";
  if (ratio <= 0.25) return "bg-amber-200 dark:bg-amber-950";
  if (ratio <= 0.5) return "bg-orange-400 dark:bg-orange-800";
  if (ratio <= 0.75) return "bg-orange-600 dark:bg-orange-600";
  return "bg-red-600 dark:bg-red-500";
};

export default function HarmonizedCalendarPage() {
  const api = useApi((options) => dashboardEstimatesCalendar(options), []);
  const [scale, setScale] = useState("viirs_harmonized");
  const [selectedYear, setSelectedYear] = useState("all");

  const rows = useMemo(
    () => (api.data?.series ?? []).filter((row) => row.scale === scale),
    [api.data, scale]
  );

  const years = useMemo(
    () => [...new Set(rows.map((row) => String(row.period).slice(0, 4)))].sort(),
    [rows]
  );

  const visible = useMemo(
    () => (selectedYear === "all" ? rows : rows.filter((row) => String(row.period).startsWith(selectedYear))),
    [rows, selectedYear]
  );

  const byYear = useMemo(() => {
    const map = new Map();
    visible.forEach((row) => {
      const year = String(row.period).slice(0, 4);
      const month = Number(String(row.period).slice(5, 7));
      if (!map.has(year)) map.set(year, new Map());
      map.get(year).set(month, row);
    });
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [visible]);

  const maxValue = useMemo(
    () => Math.max(1, ...visible.map((row) => Number(row.value) || 0)),
    [visible]
  );

  if (api.loading) return <LoadingState label="Loading harmonized estimates…" />;
  if (api.error) return <ErrorState error={api.error} onRetry={api.reload} />;
  if (!api.data || rows.length === 0) {
    return (
      <EmptyState
        title="No model estimates yet"
        description="Run modeling/run_all.sh, then import_model_outputs.py to publish the harmonized series."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold">Harmonized activity calendar</h2>
          <p className="mt-1 text-sm text-(--text-secondary)">
            One model-produced series, 2005–2025. Observed and estimated months are kept separate.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="neutral">run {api.data.run_id}</Badge>
          <Badge variant="neutral">{api.data.model_name}</Badge>
        </div>
      </div>

      <Panel
        title="Read this first"
        description="These numbers are estimates produced by the offline model, not FIRMS detections."
      >
        <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-(--text-secondary)">
          {(api.data.notes ?? []).map((note) => (
            <li key={note}>{note}</li>
          ))}
          <li>The shaded band is heuristic (±35% of the corrected value), not a fitted confidence interval.</li>
          <li>Only three observed years exist, so anomaly severity must be read with its baseline size.</li>
        </ul>
      </Panel>

      <Panel
        title="Monthly series"
        description="Blue outline = backcast year (no VIIRS observations). Cell colour is relative to the largest month shown."
      >
        <div className="mb-5 flex flex-wrap gap-2">
          {SCALES.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setScale(option.key)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                scale === option.key
                  ? "border-orange-500 bg-orange-500/10 text-orange-500"
                  : "border-(--border-color) text-(--text-secondary) hover:bg-(--surface-secondary)"
              }`}
            >
              {option.label}
            </button>
          ))}
          <select
            value={selectedYear}
            onChange={(event) => setSelectedYear(event.target.value)}
            className="rounded-lg border border-(--border-color) bg-(--surface) px-3 py-1.5 text-xs"
          >
            <option value="all">All years</option>
            {years.map((year) => (
              <option key={year} value={year}>{year}</option>
            ))}
          </select>
        </div>

        <div className="space-y-3">
          {byYear.map(([year, months]) => {
            const estimated = months.size > 0 && [...months.values()].some((row) => row.n_estimate_rows > 0);
            return (
              <div key={year} className="grid grid-cols-[4rem_1fr] items-center gap-3">
                <div className="flex flex-col items-start gap-1">
                  <span className="text-sm font-semibold">{year}</span>
                  {estimated && <Badge variant="high">estimate</Badge>}
                </div>
                <div className="grid grid-cols-12 gap-1">
                  {monthNames.map((label, index) => {
                    const row = months.get(index + 1);
                    const value = Number(row?.value ?? 0);
                    const isEstimate = Number(row?.n_estimate_rows ?? 0) > 0;
                    return (
                      <div
                        key={label}
                        title={`${label} ${year}: ${number(value)}${isEstimate ? " (estimated)" : " (observed)"}`}
                        className={`flex h-10 items-center justify-center rounded text-[10px] font-medium ${
                          levelClass(value / maxValue)
                        } ${isEstimate ? "ring-2 ring-blue-500" : ""}`}
                      >
                        {row ? number(value, { notation: "compact", maximumFractionDigits: 1 }) : "—"}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-5 flex gap-4 text-[11px] text-(--text-secondary)">
          <span>Jan — Apr — Jul — Oct — Dec</span>
          <span>Blue ring = backcast month</span>
        </div>
      </Panel>

      <Panel title="Monthly values" description="Separate observed and estimated contributions.">
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-(--surface) text-(--text-secondary)">
              <tr>
                <th className="pb-2">Month</th>
                <th className="pb-2 text-right">Total</th>
                <th className="pb-2 text-right">Observed</th>
                <th className="pb-2 text-right">Estimated</th>
                <th className="pb-2 text-right">Heuristic band</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={`${row.period}-${row.scale}`} className="border-t border-(--border-color)">
                  <td className="py-1.5">{String(row.period).slice(0, 10)}</td>
                  <td className="py-1.5 text-right font-medium">{number(row.value)}</td>
                  <td className="py-1.5 text-right">{number(row.observed_value)}</td>
                  <td className="py-1.5 text-right">{number(row.estimated_value)}</td>
                  <td className="py-1.5 text-right text-(--text-secondary)">
                    {number(row.low)} – {number(row.high)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
