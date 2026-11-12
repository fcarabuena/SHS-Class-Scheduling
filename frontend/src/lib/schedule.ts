/** Types and pure helpers shared by the teacher loading and timetable screens. */

import type { Period, Shift } from "./types";

export type Assignment = {
  id: number;
  section_id: number;
  subject_id: number;
  teacher_id: number | null;
  combined_group_id: number | null;
  required_hours: number;
  scheduled_hours: number;
};

export type Entry = {
  id: number;
  section_id: number;
  subject_id: number;
  teacher_id: number | null;
  room_id: number | null;
  day_of_week: number;
  period_id: number;
  pinned: boolean;
  combined_group_id: number | null;
};

export type Conflict = {
  key: string;
  code: string;
  severity: "error" | "incomplete";
  message: string;
  entry_ids: number[];
  teacher_id: number | null;
  room_id: number | null;
  section_id: number | null;
  subject_id: number | null;
  day_of_week: number | null;
};

export type TeacherLoad = {
  teacher_id: number;
  assigned_hours: number;
  scheduled_hours: number;
  max_daily_hours: number;
  max_weekly_hours: number;
  capacity_hours: number;
  status: "ok" | "full" | "over";
  issues: string[];
};

export type Overview = {
  semester_id: number;
  semester_number: number;
  school_year_id: number;
  days: number[];
  assignments: Assignment[];
  entries: Entry[];
  conflicts: Conflict[];
  teacher_loads: TeacherLoad[];
  summary: { errors: number; incomplete: number };
};

export type CheckCell = {
  day_of_week: number;
  period_id: number;
  status: "ok" | "current" | "conflict" | "blocked";
  swap: boolean;
  messages: string[];
};

export type Fix = {
  kind: "move" | "room" | "teacher";
  label: string;
  day_of_week: number | null;
  period_id: number | null;
  room_id: number | null;
  teacher_id: number | null;
  remaining_errors: number;
};

export type Section = {
  id: number;
  name: string;
  strand_id: number;
  grade_level: number;
  shift_id: number;
  student_count: number;
  school_year_id: number;
};
export type Subject = { id: number; code: string; name: string; hours_per_week: number; required_room_type: string };
export type Teacher = { id: number; full_name: string; is_active: boolean; qualified_subject_ids: number[] };
export type Room = { id: number; code: string; name: string; type: string; capacity: number };

export type ViewKind = "section" | "teacher" | "room";

/** What is being dragged or has been picked up with a click. */
export type Picked = { kind: "entry"; id: number } | { kind: "assignment"; id: number };

export function formatHours(hours: number): string {
  return `${Number(hours.toFixed(2))} h`;
}

export function remainingHours(assignment: Assignment): number {
  return Math.max(0, Number((assignment.required_hours - assignment.scheduled_hours).toFixed(2)));
}

export function cellKey(day: number, periodId: number): string {
  return `${day}:${periodId}`;
}

const VIEW_FIELD = { section: "section_id", teacher: "teacher_id", room: "room_id" } as const;

export function entriesForView(entries: Entry[], view: ViewKind, id: number | null): Entry[] {
  if (id === null) return [];
  return entries.filter((entry) => entry[VIEW_FIELD[view]] === id);
}

/** Classes still to be placed that belong on the current view's palette. */
export function assignmentsForView(assignments: Assignment[], view: ViewKind, id: number | null): Assignment[] {
  if (id === null || view === "room") return [];
  return assignments.filter((a) => (view === "section" ? a.section_id === id : a.teacher_id === id));
}

export type GridRow = { period: Period; shiftName: string };

/**
 * Rows of the grid. A section follows its own shift's bell schedule; a
 * teacher or room can be used in every shift, so all periods are listed in
 * clock order.
 */
export function gridRows(shifts: Shift[], shiftId: number | null): GridRow[] {
  const rows = shifts
    .filter((shift) => shiftId === null || shift.id === shiftId)
    .flatMap((shift) => shift.periods.map((period) => ({ period, shiftName: shift.name })));
  return rows.sort(
    (a, b) => a.period.start_time.localeCompare(b.period.start_time) || a.period.sort_order - b.period.sort_order,
  );
}

/** One card on the grid: a class meeting, with every section of a combined class. */
export type Meeting = { key: string; entries: Entry[] };

export function meetingsByCell(entries: Entry[]): Map<string, Meeting[]> {
  const cells = new Map<string, Meeting[]>();
  for (const entry of entries) {
    const key = cellKey(entry.day_of_week, entry.period_id);
    const meetings = cells.get(key) ?? [];
    const group = entry.combined_group_id;
    const existing = group === null ? undefined : meetings.find((m) => m.entries[0].combined_group_id === group);
    if (existing) existing.entries.push(entry);
    else meetings.push({ key: group === null ? `e${entry.id}` : `g${group}`, entries: [entry] });
    cells.set(key, meetings);
  }
  return cells;
}

/** The worst conflict level of each entry, for colouring the grid. */
export function severityByEntry(conflicts: Conflict[]): Map<number, "error" | "incomplete"> {
  const levels = new Map<number, "error" | "incomplete">();
  for (const conflict of conflicts) {
    // Under-scheduled hours are a to-do for the subject, not a fault of each class.
    if (conflict.severity !== "error") continue;
    for (const id of conflict.entry_ids) levels.set(id, "error");
  }
  return levels;
}

/** Conflicts worth listing next to the timetable currently on screen. */
export function conflictsForView(conflicts: Conflict[], entries: Entry[], view: ViewKind, id: number | null): Conflict[] {
  if (id === null) return conflicts;
  const visible = new Set(entriesForView(entries, view, id).map((entry) => entry.id));
  return conflicts.filter(
    (conflict) => conflict[VIEW_FIELD[view]] === id || conflict.entry_ids.some((entryId) => visible.has(entryId)),
  );
}

export function loadPercent(load: TeacherLoad): number {
  if (load.max_weekly_hours <= 0) return 0;
  return Math.min(100, Math.round((load.assigned_hours / load.max_weekly_hours) * 100));
}

/** Qualified teachers first; each list alphabetical. */
export function teacherChoices(teachers: Teacher[], subjectId: number): { qualified: Teacher[]; others: Teacher[] } {
  const active = teachers.filter((t) => t.is_active).sort((a, b) => a.full_name.localeCompare(b.full_name));
  return {
    qualified: active.filter((t) => t.qualified_subject_ids.includes(subjectId)),
    others: active.filter((t) => !t.qualified_subject_ids.includes(subjectId)),
  };
}
