export default function CalendarFilters({
  regions,
  region,
  onRegionChange,
  startYear,
  endYear,
  onStartYearChange,
  onEndYearChange,
  metric,
  onMetricChange,
  availableYears,
  baselineAvailable,
}) {
  const selectClass =
    "w-full rounded-lg border border-(--border-color) bg-(--surface-secondary) p-2.5 text-sm";

  return (
    <section className="rounded-xl border border-(--border-color) bg-(--surface) p-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-44 flex-1">
          <label className="mb-2 block text-sm text-(--text-secondary)">Region</label>
          <select
            value={region}
            onChange={(event) => onRegionChange(event.target.value)}
            className={selectClass}
          >
            <option value="all">All data extent</option>
            {regions.map((item) => (
              <option key={item.region} value={item.region}>
                {item.region} · {item.detections.toLocaleString("en-US")} detections
              </option>
            ))}
          </select>
        </div>

        <div className="min-w-32 flex-1">
          <label className="mb-2 block text-sm text-(--text-secondary)">From year</label>
          <select
            value={startYear ?? ""}
            onChange={(event) => onStartYearChange(Number(event.target.value))}
            className={selectClass}
          >
            {availableYears.map((year) => (
              <option key={year} value={year}>{year}</option>
            ))}
          </select>
        </div>

        <div className="min-w-32 flex-1">
          <label className="mb-2 block text-sm text-(--text-secondary)">To year</label>
          <select
            value={endYear ?? ""}
            onChange={(event) => onEndYearChange(Number(event.target.value))}
            className={selectClass}
          >
            {availableYears.map((year) => (
              <option key={year} value={year}>{year}</option>
            ))}
          </select>
        </div>

        <div className="min-w-48 flex-1">
          <label className="mb-2 block text-sm text-(--text-secondary)">Activity metric</label>
          <select
            value={metric}
            onChange={(event) => onMetricChange(event.target.value)}
            className={selectClass}
          >
            <option value="total">Total detections</option>
            <option value="modis">MODIS detections</option>
            <option value="viirs">VIIRS detections</option>
            <option value="mean_frp">Mean FRP (MW)</option>
            <option value="anomaly_percentage" disabled={!baselineAvailable}>
              Anomaly vs multi-year median{baselineAvailable ? "" : " (needs 2+ years)"}
            </option>
          </select>
        </div>
      </div>

      {!baselineAvailable && (
        <p className="mt-4 rounded-lg bg-(--surface-secondary) p-3 text-[11px] leading-5 text-(--text-secondary)">
          Historical median and anomaly percentage need at least two years of data.
          The current store holds a single year, so those metrics stay disabled instead
          of showing a fabricated baseline.
        </p>
      )}
    </section>
  );
}
