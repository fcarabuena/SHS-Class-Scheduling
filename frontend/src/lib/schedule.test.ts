import { describe, expect, it } from "vitest";

import type { Assignment, Conflict, Entry, Teacher, TeacherLoad } from "./schedule";
import {
  assignmentsForView,
  conflictCounts,
  conflictsForView,
  entriesForView,
  formatHours,
  gridRows,
  loadPercent,
  meetingsByCell,
  percentOf,
  remainingHours,
  roomUsage,
  sectionProgress,
  severityByEntry,
  teacherChoices,
} from "./schedule";
import type { Shift } from "./types";

function entry(id: number, over: Partial<Entry> = {}): Entry {
  return {
    id,
    section_id: 1,
    subject_id: 1,
    teacher_id: 1,
    room_id: 1,
    day_of_week: 1,
    period_id: 1,
    pinned: false,
    combined_group_id: null,
    ...over,
  };
}

function assignment(id: number, over: Partial<Assignment> = {}): Assignment {
  return {
    id,
    section_id: 1,
    subject_id: 1,
    teacher_id: 1,
    combined_group_id: null,
    required_hours: 4,
    scheduled_hours: 0,
    ...over,
  };
}

function conflict(over: Partial<Conflict>): Conflict {
  return {
    key: "k",
    code: "X",
    severity: "error",
    message: "",
    entry_ids: [],
    teacher_id: null,
    room_id: null,
    section_id: null,
    subject_id: null,
    day_of_week: null,
    ...over,
  };
}

const period = (id: number, shift_id: number, start: string, sort_order: number, is_break = false) => ({
  id,
  shift_id,
  name: `P${id}`,
  sort_order,
  start_time: start,
  end_time: start,
  is_break,
});

const SHIFTS: Shift[] = [
  { id: 1, name: "Morning", start_time: "06:00:00", end_time: "12:00:00", periods: [period(1, 1, "06:00:00", 1), period(2, 1, "07:00:00", 2)] },
  { id: 2, name: "Afternoon", start_time: "06:30:00", end_time: "18:00:00", periods: [period(3, 2, "06:30:00", 1)] },
];

describe("hours", () => {
  it("formats without trailing zeros", () => {
    expect(formatHours(4)).toBe("4 h");
    expect(formatHours(1.5)).toBe("1.5 h");
    expect(formatHours(0.3333)).toBe("0.33 h");
  });

  it("never reports negative remaining hours", () => {
    expect(remainingHours(assignment(1, { scheduled_hours: 1 }))).toBe(3);
    expect(remainingHours(assignment(1, { scheduled_hours: 5 }))).toBe(0);
  });
});

describe("views", () => {
  const entries = [entry(1), entry(2, { section_id: 2, teacher_id: 2 }), entry(3, { room_id: null })];

  it("filters entries by section, teacher or room", () => {
    expect(entriesForView(entries, "section", 1).map((e) => e.id)).toEqual([1, 3]);
    expect(entriesForView(entries, "teacher", 2).map((e) => e.id)).toEqual([2]);
    expect(entriesForView(entries, "room", 1).map((e) => e.id)).toEqual([1, 2]);
    expect(entriesForView(entries, "room", null)).toEqual([]);
  });

  it("lists placeable classes for a section or teacher but not for a room", () => {
    const all = [assignment(1), assignment(2, { section_id: 2, teacher_id: 2 })];
    expect(assignmentsForView(all, "section", 2).map((a) => a.id)).toEqual([2]);
    expect(assignmentsForView(all, "teacher", 1).map((a) => a.id)).toEqual([1]);
    expect(assignmentsForView(all, "room", 1)).toEqual([]);
  });

  it("uses one shift's periods for a section and all periods in clock order otherwise", () => {
    expect(gridRows(SHIFTS, 1).map((r) => r.period.id)).toEqual([1, 2]);
    expect(gridRows(SHIFTS, null).map((r) => r.period.id)).toEqual([1, 3, 2]);
    expect(gridRows(SHIFTS, null)[1].shiftName).toBe("Afternoon");
  });
});

describe("grid cells", () => {
  it("shows a combined class as one meeting and a clash as two", () => {
    const cells = meetingsByCell([
      entry(1, { combined_group_id: 9 }),
      entry(2, { combined_group_id: 9, section_id: 2 }),
      entry(3, { section_id: 3 }),
      entry(4, { day_of_week: 2 }),
    ]);
    const monday = cells.get("1:1")!;
    expect(monday.map((m) => m.entries.map((e) => e.id))).toEqual([[1, 2], [3]]);
    expect(cells.get("2:1")!.length).toBe(1);
  });

  it("marks only entries with hard conflicts", () => {
    const levels = severityByEntry([
      conflict({ entry_ids: [1, 2] }),
      conflict({ severity: "incomplete", entry_ids: [3] }),
    ]);
    expect([...levels.keys()]).toEqual([1, 2]);
  });

  it("keeps conflicts that touch the timetable on screen", () => {
    const entries = [entry(1), entry(2, { section_id: 2 })];
    const all = [
      conflict({ key: "a", entry_ids: [1, 2] }),
      conflict({ key: "b", entry_ids: [2] }),
      conflict({ key: "c", severity: "incomplete", section_id: 1 }),
    ];
    expect(conflictsForView(all, entries, "section", 1).map((c) => c.key)).toEqual(["a", "c"]);
    expect(conflictsForView(all, entries, "section", null).length).toBe(3);
  });
});

describe("teacher loading", () => {
  const load = (assigned: number, max: number): TeacherLoad => ({
    teacher_id: 1,
    assigned_hours: assigned,
    scheduled_hours: 0,
    max_daily_hours: 6,
    max_weekly_hours: max,
    capacity_hours: max,
    status: "ok",
    issues: [],
  });

  it("caps the load bar at 100 percent", () => {
    expect(loadPercent(load(15, 30))).toBe(50);
    expect(loadPercent(load(45, 30))).toBe(100);
    expect(loadPercent(load(5, 0))).toBe(0);
  });

  it("offers qualified, active teachers first", () => {
    const teachers: Teacher[] = [
      { id: 1, full_name: "Zeny", is_active: true, qualified_subject_ids: [7] },
      { id: 2, full_name: "Abel", is_active: true, qualified_subject_ids: [] },
      { id: 3, full_name: "Ana", is_active: true, qualified_subject_ids: [7, 8] },
      { id: 4, full_name: "Gone", is_active: false, qualified_subject_ids: [7] },
    ];
    const choices = teacherChoices(teachers, 7);
    expect(choices.qualified.map((t) => t.full_name)).toEqual(["Ana", "Zeny"]);
    expect(choices.others.map((t) => t.full_name)).toEqual(["Abel"]);
  });
});

describe("dashboard figures", () => {
  const section = (id: number, name: string) => ({
    id, name, strand_id: 1, grade_level: 11, shift_id: 1, student_count: 40, school_year_id: 1,
  });

  it("totals placed and required hours per section without counting extra hours", () => {
    const meters = sectionProgress(
      [
        assignment(1, { required_hours: 4, scheduled_hours: 2 }),
        assignment(2, { required_hours: 1, scheduled_hours: 3 }),
        assignment(3, { section_id: 2, required_hours: 2, scheduled_hours: 2 }),
      ],
      [section(1, "11-A"), section(2, "11-B"), section(3, "11-C")],
    );
    expect(meters.map((m) => [m.label, m.value, m.max])).toEqual([["11-A", 3, 5], ["11-B", 2, 2], ["11-C", 0, 0]]);
    expect(percentOf(3, 5)).toBe(60);
    expect(percentOf(0, 0)).toBe(0);
  });

  it("measures room use against the school week, counting overlapping shifts and combined classes once", () => {
    const hour = (id: number, shift_id: number, start: string, end: string, is_break = false) => ({
      id, shift_id, name: `P${id}`, sort_order: id, start_time: start, end_time: end, is_break,
    });
    const shifts: Shift[] = [
      { id: 1, name: "AM", start_time: "07:00:00", end_time: "09:30:00", periods: [hour(1, 1, "07:00:00", "08:00:00"), hour(2, 1, "08:00:00", "09:00:00"), hour(9, 1, "09:00:00", "09:30:00", true)] },
      { id: 2, name: "PM", start_time: "08:30:00", end_time: "10:00:00", periods: [hour(3, 2, "08:30:00", "10:00:00")] },
    ];
    const rooms = [{ id: 1, code: "R1", name: "Room 1", type: "lecture", capacity: 45 }, { id: 2, code: "R2", name: "Room 2", type: "lecture", capacity: 45 }];
    const entries = [
      entry(1, { combined_group_id: 5 }),
      entry(2, { combined_group_id: 5, section_id: 2 }),
      entry(3, { day_of_week: 2, period_id: 3 }),
      entry(4, { room_id: null }),
    ];
    // 07:00-10:00 is 3 h of teaching time a day, 15 h over five days.
    expect(roomUsage(entries, rooms, shifts, [1, 2, 3, 4, 5])).toEqual([
      { id: 1, label: "Room 1", value: 2.5, max: 15 },
      { id: 2, label: "Room 2", value: 0, max: 15 },
    ]);
  });

  it("counts conflicts by kind, most frequent first", () => {
    const counts = conflictCounts([
      conflict({ code: "ROOM_TOO" }),
      conflict({ code: "TEACHER_DOUBLE_BOOKED" }),
      conflict({ code: "TEACHER_DOUBLE_BOOKED" }),
    ]);
    expect(counts.map((c) => [c.label, c.count])).toEqual([["Teacher in two classes at once", 2], ["ROOM_TOO", 1]]);
  });
});
