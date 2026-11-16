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

import {
  dashboardCalendar,
  monthlyAnalytics,
  observationCountries,
  observationStatistics,
} from "../../api/endpoints";
import Panel from "../../components/common/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import { decimal, number } from "../../lib/format";

export default function CalendarPage() {
  // الدول اللي فيها detections (بعد تشغيل tools/assign_countries.py)
  const countriesApi = useApi((options) => observationCountries(options), []);
  const countryOptions = useMemo(
    () =>
      (countriesApi.data ?? []).map((item) => ({
       region: item.code ?? item.iso_a3,
        label: item.name ?? item.country,
        detections: item.detections,
      })),
    [countriesApi.data]
  );

  // تواريخ أول وآخر detection في الداتا، عشان نعرف الشهور الناقصة
  const statsApi = useApi((options) => observationStatistics(options), []);
  const coverage = statsApi.data?.overall ?? null;

  const [region, setRegion] = useState("all");
  const [metric, setMetric] = useState("total");
  const [yearRange, setYearRange] = useState({ start: null, end: null });
  const [selection, setSelection] = useState({ year: null, month: null });
  const [selectedDay, setSelectedDay] = useState(null);

  const country = region === "all" ? undefined : region;

  const monthlyApi = useApi(
    (options) => monthlyAnalytics({ ...options, country }),
    [country]
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

  // الشهر الأول والأخير ناقصين لو الداتا ما بتغطيش الشهر كله
  const partialMonths = useMemo(() => {
    const keys = new Set();
    if (!coverage?.first_detection_utc || !coverage?.last_detection_utc) return keys;
    const first = new Date(coverage.first_detection_utc);
    const last = new Date(coverage.last_detection_utc);
    if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime())) return keys;

    const firstYear = first.getUTCFullYear();
    const firstMonth = first.getUTCMonth() + 1;
    const lastYear = last.getUTCFullYear();
    const lastMonth = last.getUTCMonth() + 1;

    if (first.getUTCDate() > 1) keys.add(`${firstYear}-${firstMonth}`);
    if (last.getUTCDate() < daysInMonth(lastYear, lastMonth)) {
      keys.add(`${lastYear}-${lastMonth}`);
    }
    return keys;
  }, [coverage]);

  // علامة الشهر الناقص + مقارنة كل شهر بمتوسط باقي الشهور الكاملة في نفس السنة
  const heatmapData = useMemo(() => {
    const flagged = filtered.map((item) => ({
      ...item,
      partial: partialMonths.has(`${item.year}-${item.month}`),
    }));

    const fullByYear = new Map();
    for (const item of flagged) {
      if (item.partial) continue;
      const list = fullByYear.get(item.year) ?? [];
      list.push(item);
      fullByYear.set(item.year, list);
    }

    return flagged.map((item) => {
      let vsYearPct = null;
      if (!item.partial) {
        const others = (fullByYear.get(item.year) ?? []).filter(
          (other) => other.month !== item.month
        );
        if (others.length >= 3) {
          const mean = others.reduce((sum, other) => sum + other.total, 0) / others.length;
          if (mean > 0) vsYearPct = ((item.total - mean) / mean) * 100;
        }
      }
      return { ...item, vs_year_pct: vsYearPct };
    });
  }, [filtered, partialMonths]);

  // الاختيار الافتراضي: آخر شهر كامل فيه داتا
  const latestWithData = useMemo(() => {
    const reversed = [...heatmapData].reverse();
    return (
      reversed.find((item) => item.total > 0 && !item.partial) ??
      reversed.find((item) => item.total > 0) ??
      heatmapData.at(-1) ??
      null
    );
  }, [heatmapData]);

  const selectedYear = selection.year ?? latestWithData?.year ?? null;
  const selectedMonth = selection.month ?? latestWithData?.month ?? null;
  const selectedPartial = partialMonths.has(`${selectedYear}-${selectedMonth}`);

  const selectedMonthData = useMemo(
    () =>
      heatmapData.find(
        (item) => item.year === selectedYear && item.month === selectedMonth
      ) ?? null,
    [heatmapData, selectedYear, selectedMonth]
  );

  const monthStart = selectedYear && selectedMonth
    ? isoDate(selectedYear, selectedMonth, 1)
    : undefined;
  const monthEnd = selectedYear && selectedMonth
    ? isoDate(selectedYear, selectedMonth, daysInMonth(selectedYear, selectedMonth))
    : undefined;

  const dailyApi = useApi(
    (options) =>
      dashboardCalendar({ ...options, country, start: monthStart, end: monthEnd }),
    [country, monthStart, monthEnd]
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

  const coverageText =
    coverage?.first_detection_utc && coverage?.last_detection_utc
      ? `${coverage.first_detection_utc.slice(0, 10)} → ${coverage.last_detection_utc.slice(0, 10)}`
      : "";

  return (
    <div className="space-y-7">
      <div>
        <h2 className="text-2xl font-bold">Activity calendar</h2>
        <p className="mt-1 text-sm text-(--text-secondary)">
          Harmonized burning calendar built from the stored MODIS and VIIRS detections.
        </p>
      </div>

      <CalendarFilters
        regions={countryOptions}
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

      {countriesApi.error && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
          Country list unavailable ({String(countriesApi.error?.message ?? "error")}). Run
          <code className="mx-1">python tools/assign_countries.py</code> in the backend, then reload.
        </p>
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
            description="Import source files and aggregate them, or choose another country."
          />
        </Panel>
      )}

      {filtered.length > 0 && (
        <>
          <YearlyHeatmap
            data={heatmapData}
            metric={metric}
            onMonthSelect={handleMonthSelect}
            selected={{ year: selectedYear, month: selectedMonth }}
          />

          <div>
            <h3 className="mb-4 text-lg font-semibold">
              {monthNames[(selectedMonth ?? 1) - 1]} {selectedYear} summary
            </h3>
            {selectedPartial && (
              <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                Partial month: the stored data covers only part of this month
                {coverageText ? ` (data range ${coverageText})` : ""}. Its totals are not
                comparable with full months.
              </p>
            )}
            {selectedMonthData ? (
              <MonthSummary data={selectedMonthData} dailyStats={dailyStats} />
            ) : (
              <Panel>
                <EmptyState
                  title="No data for this month"
                  description="The selected month has no stored detections for this country."
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