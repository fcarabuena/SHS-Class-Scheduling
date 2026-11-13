export type Role = "admin" | "scheduler" | "teacher";

export type User = {
  id: number;
  school_id: number;
  email: string;
  full_name: string;
  role: Role;
  teacher_id: number | null;
  is_active: boolean;
  is_platform_admin?: boolean;
};

/** Fired after notifications are read, so the menu's unread count refreshes. */
export const NOTIFICATIONS_EVENT = "shs:notifications";

export type SchoolSettings = {
  default_max_daily_hours: number;
  default_max_weekly_hours: number;
  school_days: number[];
  [key: string]: unknown;
};

export type School = {
  id: number;
  name: string;
  deped_school_id: string | null;
  address: string | null;
  division: string | null;
  region: string | null;
  logo_url: string | null;
  settings: SchoolSettings;
  onboarding_completed: boolean;
};

export type Semester = { id: number; number: number; start_date: string; end_date: string; is_active: boolean };
export type SchoolYear = {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
  semesters: Semester[];
};

export type Period = {
  id: number;
  shift_id: number;
  name: string;
  sort_order: number;
  start_time: string;
  end_time: string;
  is_break: boolean;
};
export type Shift = { id: number; name: string; start_time: string; end_time: string; periods: Period[] };

export type Availability = { day_of_week: number; period_id: number; kind: "unavailable" | "preferred" };

// Rows of the generic CRUD pages are handled as loose records.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;

export const DAY_NAMES: Record<number, string> = {
  1: "Mon",
  2: "Tue",
  3: "Wed",
  4: "Thu",
  5: "Fri",
  6: "Sat",
};

export const ROOM_TYPES = [
  { value: "lecture", label: "Lecture room" },
  { value: "computer_lab", label: "Computer lab" },
  { value: "science_lab", label: "Science lab" },
  { value: "shop", label: "Shop" },
  { value: "home_economics", label: "Home economics" },
  { value: "gym", label: "Gym / court" },
];

export const SUBJECT_TYPES = [
  { value: "core", label: "Core" },
  { value: "applied", label: "Applied" },
  { value: "specialized", label: "Specialized" },
];

export const ROLES = [
  { value: "admin", label: "Admin" },
  { value: "scheduler", label: "Scheduler" },
  { value: "teacher", label: "Teacher (read-only)" },
];

export function labelOf(options: { value: string; label: string }[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

export function shortTime(value: string): string {
  return value.slice(0, 5);
}
