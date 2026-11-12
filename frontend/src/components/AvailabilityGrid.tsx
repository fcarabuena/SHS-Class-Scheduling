"use client";

import type { Availability, Shift } from "@/lib/types";
import { DAY_NAMES, shortTime } from "@/lib/types";

type Props = {
  shifts: Shift[];
  days: number[];
  value: Availability[];
  onChange: (value: Availability[]) => void;
};

const NEXT_KIND = { none: "unavailable", unavailable: "preferred", preferred: "none" } as const;

const CELL = {
  none: { text: "", label: "no preference", style: "bg-white text-stone-400 hover:bg-stone-100" },
  unavailable: { text: "✕", label: "unavailable", style: "bg-red-100 font-semibold text-red-800" },
  preferred: { text: "★", label: "preferred", style: "bg-emerald-100 font-semibold text-emerald-900" },
};

/** Click a slot to cycle: no preference → unavailable → preferred. */
export function AvailabilityGrid({ shifts, days, value, onChange }: Props) {
  const kindOf = (day: number, periodId: number) =>
    value.find((slot) => slot.day_of_week === day && slot.period_id === periodId)?.kind ?? "none";

  function cycle(day: number, periodId: number) {
    const next = NEXT_KIND[kindOf(day, periodId)];
    const rest = value.filter((slot) => !(slot.day_of_week === day && slot.period_id === periodId));
    onChange(next === "none" ? rest : [...rest, { day_of_week: day, period_id: periodId, kind: next }]);
  }

  const withPeriods = shifts.filter((shift) => shift.periods.some((period) => !period.is_break));
  if (withPeriods.length === 0) {
    return <p className="text-sm text-stone-500">Set up a bell schedule first to mark time slots.</p>;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-stone-600">
        Click a slot to change it: blank = no preference, <span className="font-semibold text-red-800">✕ unavailable</span>{" "}
        (never scheduled), <span className="font-semibold text-emerald-900">★ preferred</span>.
      </p>
      {withPeriods.map((shift) => (
        <div key={shift.id} className="overflow-x-auto">
          <table className="w-full min-w-[26rem] border-collapse text-sm">
            <caption className="mb-1 text-left text-xs font-semibold uppercase tracking-wide text-stone-600">
              {shift.name} shift
            </caption>
            <thead>
              <tr>
                <th scope="col" className="border border-stone-200 bg-stone-100 px-2 py-1 text-left font-medium">
                  Period
                </th>
                {days.map((day) => (
                  <th key={day} scope="col" className="border border-stone-200 bg-stone-100 px-2 py-1 font-medium">
                    {DAY_NAMES[day]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shift.periods
                .filter((period) => !period.is_break)
                .map((period) => (
                  <tr key={period.id}>
                    <th scope="row" className="whitespace-nowrap border border-stone-200 px-2 py-1 text-left font-normal">
                      {period.name}{" "}
                      <span className="text-xs text-stone-500">
                        {shortTime(period.start_time)}–{shortTime(period.end_time)}
                      </span>
                    </th>
                    {days.map((day) => {
                      const cell = CELL[kindOf(day, period.id)];
                      return (
                        <td key={day} className="border border-stone-200 p-0">
                          <button
                            type="button"
                            className={`block h-8 w-full ${cell.style}`}
                            aria-label={`${DAY_NAMES[day]} ${period.name}: ${cell.label}`}
                            onClick={() => cycle(day, period.id)}
                          >
                            {cell.text}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
