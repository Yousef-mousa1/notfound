import { useMemo } from "react";
import { daysInMonth, isoDate } from "../utils/calendarHelpers";
import { number } from "../../../lib/format";

export default function DailyCalendar({ year, month, data, onDaySelect, selectedDay }) {
  const totalDays = daysInMonth(year, month);
  const firstDay = (new Date(year, month - 1, 1).getDay() + 6) % 7; // Monday = 0

  const dailyMap = useMemo(
    () => new Map(data.map((item) => [item.date, item])),
    [data]
  );

  const maxCount = useMemo(
    () => Math.max(1, ...data.map((item) => item.total ?? 0)),
    [data]
  );

  function getDayStyle(item) {
    if (!item) return "bg-(--surface-secondary) text-(--text-secondary)";
    if (!item.total) return "bg-slate-100 dark:bg-slate-800";

    const ratio = item.total / maxCount;
    if (ratio <= 0.25) return "bg-amber-200 dark:bg-amber-950 text-amber-950 dark:text-amber-100";
    if (ratio <= 0.5) return "bg-orange-400 text-orange-950";
    if (ratio <= 0.75) return "bg-orange-600 text-white";
    return "bg-red-600 text-white";
  }

  return (
    <section className="rounded-xl border border-(--border-color) bg-(--surface) p-5">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">Daily activity — {month}/{year}</h3>
        <span className="text-[11px] text-(--text-secondary)">
          {number(data.length)} of {totalDays} days have detections
        </span>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
          <div key={day} className="pb-2 text-center text-xs font-medium text-(--text-secondary)">
            {day}
          </div>
        ))}

        {Array.from({ length: firstDay }).map((_, index) => (
          <div key={`empty-${index}`} />
        ))}

        {Array.from({ length: totalDays }, (_, index) => index + 1).map((day) => {
          const date = isoDate(year, month, day);
          const item = dailyMap.get(date);
          const isSelected = selectedDay?.date === date;

          return (
            <button
              key={day}
              type="button"
              onClick={() => item && onDaySelect?.(item)}
              disabled={!item}
              title={
                item
                  ? `${date} · ${number(item.total)} detections (MODIS ${number(item.modis)}, VIIRS ${number(item.viirs)})`
                  : `${date} · no detection recorded (may be no fire or no observation)`
              }
              className={`
                flex aspect-square min-h-10 flex-col items-center justify-center gap-0.5
                rounded-lg text-sm font-medium transition ${getDayStyle(item)}
                ${item ? "cursor-pointer hover:ring-2 hover:ring-orange-500" : "cursor-not-allowed"}
                ${isSelected ? "ring-2 ring-orange-500 ring-offset-2 dark:ring-offset-gray-900" : ""}
              `}
            >
              <span>{day}</span>
              {item && <span className="text-[9px] opacity-80">{number(item.total)}</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-5 flex flex-wrap gap-4 text-[11px] text-(--text-secondary)">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-amber-200 dark:bg-amber-950" /> Few detections
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-orange-600" /> Many
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-red-600" /> Most
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded border border-(--border-color) bg-(--surface-secondary)" /> No detection recorded
        </span>
      </div>

      <p className="mt-2 text-[11px] leading-5 text-(--text-secondary)">
        Source files contain detections only. A missing day is not proof of no fire: it may
        be no observation (cloud, overpass gap) or a valid observation without fire.
      </p>
    </section>
  );
}
