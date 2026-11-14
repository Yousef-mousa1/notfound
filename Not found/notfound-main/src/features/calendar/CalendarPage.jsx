import { useMemo, useState } from "react";

import CalendarFilters from "./components/CalendarFilters";
import DailyCalendar from "./components/DailyCalendar";
import MonthSummary from "./components/MonthSummary";
import YearlyHeatmap from "./components/YearlyHeatmap";

import {
  addHistoricalBaseline,
  buildMonthlySeries,
  daysInMonth,
  isoDate,
  monthNames,
} from "./utils/calendarHelpers";

import { analyticsRegions, dashboardCalendar, monthlyAnalytics } from "../../api/endpoints";
import Panel from "../../components/common/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import { decimal, number } from "../../lib/format";

const bboxOf = (regions, code) => {
  const region = regions.find((item) => item.region === code);
  if (!region) return undefined;
  const { min_lon, min_lat, max_lon, max_lat } = region.bbox;
  return `${min_lon},${min_lat},${max_lon},${max_lat}`;
};

export default function CalendarPage() {
  const regionsApi = useApi((options) => analyticsRegions(options), []);
  const regions = regionsApi.data ?? [];

  const [region, setRegion] = useState("all");
  const [metric, setMetric] = useState("total");
  const [yearRange, setYearRange] = useState({ start: null, end: null });
  const [selection, setSelection] = useState({ year: null, month: null });
  const [selectedDay, setSelectedDay] = useState(null);

  const bbox = region === "all" ? undefined : bboxOf(regions, region);

  const monthlyApi = useApi(
    (options) => monthlyAnalytics({ ...options, bbox }),
    [bbox]
  );

  const series = useMemo(
    () => addHistoricalBaseline(buildMonthlySeries(monthlyApi.data?.series ?? [])),
    [monthlyApi.data]
  );

  const availableYears = useMemo(
    () => [...new Set(series.map((item) => item.year))].sort((a, b) => a - b),
    [series]
  );

  const startYear = yearRange.start ?? availableYears[0] ?? null;
  const endYear = yearRange.end ?? availableYears.at(-1) ?? null;

  const filtered = useMemo(
    () =>
      series.filter(
        (item) => item.year >= startYear && item.year <= endYear
      ),
    [series, startYear, endYear]
  );

  const latestWithData = useMemo(
    () => [...filtered].reverse().find((item) => item.total > 0) ?? filtered.at(-1) ?? null,
    [filtered]
  );

  const selectedYear = selection.year ?? latestWithData?.year ?? null;
  const selectedMonth = selection.month ?? latestWithData?.month ?? null;

  const selectedMonthData = useMemo(
    () =>
      filtered.find(
        (item) => item.year === selectedYear && item.month === selectedMonth
      ) ?? null,
    [filtered, selectedYear, selectedMonth]
  );

  const monthStart = selectedYear && selectedMonth
    ? isoDate(selectedYear, selectedMonth, 1)
    : undefined;
  const monthEnd = selectedYear && selectedMonth
    ? isoDate(selectedYear, selectedMonth, daysInMonth(selectedYear, selectedMonth))
    : undefined;

  const dailyApi = useApi(
    (options) =>
      dashboardCalendar({ ...options, bbox, start: monthStart, end: monthEnd }),
    [bbox, monthStart, monthEnd]
  );

  const daily = useMemo(() => {
    const map = new Map();
    (dailyApi.data?.series ?? []).forEach((row) => {
      const entry = map.get(row.bucket) ?? { date: row.bucket, modis: 0, viirs: 0, total: 0 };
      entry[row.sensor] = row.detections;
      entry.total += row.detections;
      map.set(row.bucket, entry);
    });
    return [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [dailyApi.data]);

  const dailyStats = useMemo(() => {
    if (!daily.length) return { activeDays: 0, perSensor: {} };
    return {
      activeDays: daily.length,
      perSensor: {
        modis: daily.filter((item) => item.modis > 0).length,
        viirs: daily.filter((item) => item.viirs > 0).length,
      },
    };
  }, [daily]);

  function handleStartYearChange(year) {
    setYearRange({
      start: year,
      end: endYear !== null && year > endYear ? year : endYear,
    });
    setSelectedDay(null);
  }

  function handleEndYearChange(year) {
    setYearRange({
      start: startYear !== null && year < startYear ? year : startYear,
      end: year,
    });
    setSelectedDay(null);
  }

  function handleMonthSelect(year, month) {
    setSelection({ year, month });
    setSelectedDay(null);
  }

  function handleRegionChange(code) {
    setRegion(code);
    setYearRange({ start: null, end: null });
    setSelection({ year: null, month: null });
    setSelectedDay(null);
  }

  const baselineAvailable = availableYears.length >= 2;

  return (
    <div className="space-y-7">
      <div>
        <h2 className="text-2xl font-bold">Activity calendar</h2>
        <p className="mt-1 text-sm text-(--text-secondary)">
          Harmonized burning calendar built from the stored MODIS and VIIRS detections.
        </p>
      </div>

      {regionsApi.loading && (
        <Panel>
          <LoadingState label="Loading regions…" />
        </Panel>
      )}

      {regionsApi.error && (
        <Panel>
          <ErrorState error={regionsApi.error} onRetry={regionsApi.reload} />
        </Panel>
      )}

      {!regionsApi.loading && !regionsApi.error && (
        <CalendarFilters
          regions={regions}
          region={region}
          onRegionChange={handleRegionChange}
          startYear={startYear}
          endYear={endYear}
          onStartYearChange={handleStartYearChange}
          onEndYearChange={handleEndYearChange}
          metric={metric}
          onMetricChange={setMetric}
          availableYears={availableYears}
          baselineAvailable={baselineAvailable}
        />
      )}

      {monthlyApi.loading && (
        <Panel>
          <LoadingState label="Loading monthly activity…" />
        </Panel>
      )}

      {monthlyApi.error && (
        <Panel>
          <ErrorState error={monthlyApi.error} onRetry={monthlyApi.reload} />
        </Panel>
      )}

      {!monthlyApi.loading && !monthlyApi.error && filtered.length === 0 && (
        <Panel>
          <EmptyState
            title="No monthly activity for this selection"
            description="Import source files and aggregate them, or choose another region."
          />
        </Panel>
      )}

      {filtered.length > 0 && (
        <>
          <YearlyHeatmap
            data={filtered}
            metric={metric}
            onMonthSelect={handleMonthSelect}
            selected={{ year: selectedYear, month: selectedMonth }}
          />

          <div>
            <h3 className="mb-4 text-lg font-semibold">
              {monthNames[(selectedMonth ?? 1) - 1]} {selectedYear} summary
            </h3>
            {selectedMonthData ? (
              <MonthSummary data={selectedMonthData} dailyStats={dailyStats} />
            ) : (
              <Panel>
                <EmptyState
                  title="No data for this month"
                  description="The selected month has no stored detections in this region."
                />
              </Panel>
            )}
          </div>

          {dailyApi.error && (
            <Panel>
              <ErrorState error={dailyApi.error} onRetry={dailyApi.reload} />
            </Panel>
          )}

          {dailyApi.loading && (
            <Panel>
              <LoadingState label="Loading daily detections…" />
            </Panel>
          )}

          {!dailyApi.loading && !dailyApi.error && selectedYear && selectedMonth && (
            <DailyCalendar
              year={selectedYear}
              month={selectedMonth}
              data={daily}
              onDaySelect={setSelectedDay}
              selectedDay={selectedDay}
            />
          )}

          {selectedDay && (
            <div className="rounded-xl border border-orange-500/30 bg-(--surface) p-5">
              <h3 className="font-semibold">Selected day: {selectedDay.date}</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-(--text-secondary)">MODIS detections</p>
                  <p className="text-lg font-bold">{number(selectedDay.modis)}</p>
                </div>
                <div>
                  <p className="text-xs text-(--text-secondary)">VIIRS detections</p>
                  <p className="text-lg font-bold">{number(selectedDay.viirs)}</p>
                </div>
                <div>
                  <p className="text-xs text-(--text-secondary)">Total</p>
                  <p className="text-lg font-bold">{number(selectedDay.total)}</p>
                </div>
              </div>
              <p className="mt-3 text-[11px] leading-5 text-(--text-secondary)">
                One MODIS detection is not equal to one VIIRS detection: the sensors have
                different pixel sizes (≈1 km vs 375 m). Compare counts within a sensor,
                not across sensors. Mean FRP for this month: {decimal(selectedMonthData?.mean_frp)} MW.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
