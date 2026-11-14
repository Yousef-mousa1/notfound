import {
  monthNames,
  getActivityLevel,
  getActivityColor,
  getAnomalyColor,
} from "../utils/calendarHelpers";
import { decimal, number } from "../../../lib/format";

const METRIC_LABELS = {
  total: "Total detections",
  modis: "MODIS detections",
  viirs: "VIIRS detections",
  mean_frp: "Mean FRP (MW)",
  anomaly_percentage: "Anomaly vs multi-year median (%)",
};

function formatValue(metric, value) {
  if (value === null || value === undefined) return "—";
  if (metric === "mean_frp") return `${decimal(value)} MW`;
  if (metric === "anomaly_percentage") return `${value > 0 ? "+" : ""}${decimal(value)}%`;
  return number(value);
}

export default function YearlyHeatmap({ data, metric, onMonthSelect, selected }) {
  const values = data
    .map((item) => item[metric])
    .filter((value) => value !== null && value !== undefined);

  const maxValue = Math.max(...values.map(Math.abs), 1);
  const years = [...new Set(data.map((item) => item.year))].sort((a, b) => a - b);

  function cellColor(item) {
    const value = item?.[metric];
    if (value === null || value === undefined) return getActivityColor("no-data");
    if (metric === "anomaly_percentage") return getAnomalyColor(value);
    return getActivityColor(getActivityLevel(value, maxValue));
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-(--border-color) bg-(--surface) p-5">
      <div className="mb-5">
        <h3 className="text-lg font-semibold">Yearly fire activity</h3>
        <p className="mt-1 text-xs text-(--text-secondary)">
          Displaying: {METRIC_LABELS[metric] ?? metric}. Select a month to open its daily calendar.
        </p>
      </div>

      <div className="min-w-162.5">
        <div className="mb-3 grid grid-cols-[70px_repeat(12,minmax(0,1fr))] gap-2">
          <div />
          {monthNames.map((month) => (
            <div key={month} className="text-center text-xs font-medium text-(--text-secondary)">
              {month}
            </div>
          ))}
        </div>

        <div className="space-y-3">
          {years.map((year) => (
            <div key={year} className="grid grid-cols-[70px_repeat(12,minmax(0,1fr))] items-center gap-2">
              <span className="text-sm font-semibold">{year}</span>

              {monthNames.map((month, index) => {
                const monthNumber = index + 1;
                const item = data.find(
                  (entry) => entry.year === year && entry.month === monthNumber
                );
                const value = item?.[metric];
                const isSelected =
                  selected?.year === year && selected?.month === monthNumber;

                return (
                  <button
                    key={`${year}-${monthNumber}`}
                    type="button"
                    disabled={!item || value === null || value === undefined}
                    onClick={() => item && onMonthSelect?.(year, monthNumber)}
                    title={
                      item
                        ? [
                            `${month} ${year}`,
                            `Total: ${number(item.total)}`,
                            `MODIS: ${number(item.modis)}`,
                            `VIIRS: ${number(item.viirs)}`,
                            item.mean_frp !== null ? `Mean FRP: ${decimal(item.mean_frp)} MW` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")
                        : `${month} ${year}: no detections recorded`
                    }
                    className={`
                      h-9 rounded-md text-[10px] font-medium text-white/90 transition
                      ${cellColor(item)}
                      ${item && value !== null ? "cursor-pointer hover:ring-2 hover:ring-orange-500 hover:ring-offset-2 dark:hover:ring-offset-gray-900" : "cursor-not-allowed opacity-40"}
                      ${isSelected ? "ring-2 ring-orange-500 ring-offset-2 dark:ring-offset-gray-900" : ""}
                    `}
                  >
                    {value !== null && value !== undefined ? formatValue(metric, value) : ""}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-4 text-[11px] text-(--text-secondary)">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-amber-200 dark:bg-amber-950" /> Low
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-orange-400" /> Medium
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-orange-600" /> High
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-red-600" /> Very high
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-(--surface-secondary) opacity-40" /> No data
        </span>
      </div>
    </div>
  );
}
