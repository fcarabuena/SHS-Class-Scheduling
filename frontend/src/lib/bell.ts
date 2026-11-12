/** Bell-schedule helpers used by the onboarding wizard. Times are "HH:MM". */

export type PeriodRow = { name: string; start_time: string; end_time: string; is_break: boolean };

export function toMinutes(time: string): number {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
}

export function fromMinutes(total: number): string {
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export type GenerateOptions = {
  start: string;
  periodMinutes: number;
  periodCount: number;
  /** Insert a break after this many periods (0 = no break). */
  breakAfter: number;
  breakMinutes: number;
  breakName?: string;
};

export function generateBellSchedule(options: GenerateOptions): PeriodRow[] {
  const rows: PeriodRow[] = [];
  let cursor = toMinutes(options.start);
  for (let index = 1; index <= options.periodCount; index++) {
    rows.push({
      name: `Period ${index}`,
      start_time: fromMinutes(cursor),
      end_time: fromMinutes(cursor + options.periodMinutes),
      is_break: false,
    });
    cursor += options.periodMinutes;
    const breakDue = options.breakAfter > 0 && index === options.breakAfter && index < options.periodCount;
    if (breakDue && options.breakMinutes > 0) {
      rows.push({
        name: options.breakName ?? "Break",
        start_time: fromMinutes(cursor),
        end_time: fromMinutes(cursor + options.breakMinutes),
        is_break: true,
      });
      cursor += options.breakMinutes;
    }
  }
  return rows;
}

/** Returns a message describing the first problem, or null if the rows are valid. */
export function validateBellSchedule(rows: PeriodRow[], shiftStart: string, shiftEnd: string): string | null {
  if (!rows.some((row) => !row.is_break)) return "Add at least one class period.";
  let previousEnd = toMinutes(shiftStart);
  for (const [index, row] of rows.entries()) {
    const label = `Row ${index + 1} (${row.name || "unnamed"})`;
    if (!row.name.trim()) return `Row ${index + 1} needs a name.`;
    if (!row.start_time || !row.end_time) return `${label} needs a start and end time.`;
    const start = toMinutes(row.start_time);
    const end = toMinutes(row.end_time);
    if (end <= start) return `${label} must end after it starts.`;
    if (start < previousEnd) {
      return index === 0
        ? `${label} starts before the shift starts (${shiftStart}).`
        : `${label} overlaps the row before it.`;
    }
    if (end > toMinutes(shiftEnd)) return `${label} ends after the shift ends (${shiftEnd}).`;
    previousEnd = end;
  }
  return null;
}
