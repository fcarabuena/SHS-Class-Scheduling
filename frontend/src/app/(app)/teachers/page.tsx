"use client";

import { AvailabilityGrid } from "@/components/AvailabilityGrid";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Availability, Shift } from "@/lib/types";

export default function TeachersPage() {
  const { school } = useAuth();
  const days = school?.settings.school_days ?? [1, 2, 3, 4, 5];
  const dailyDefault = school?.settings.default_max_daily_hours ?? 6;
  const weeklyDefault = school?.settings.default_max_weekly_hours ?? 30;

  return (
    <ResourcePage
      title="Teachers"
      description="Teachers with the subjects they are qualified to teach, their load limits, and the time slots they cannot or prefer to teach."
      endpoint="/api/teachers"
      importResource="teachers"
      lookups={{ subjects: "/api/subjects", shifts: "/api/shifts" }}
      wideForm
      columns={[
        { header: "Employee ID", cell: (row) => <span className="whitespace-nowrap font-medium">{row.employee_id}</span> },
        {
          header: "Name",
          cell: (row) => (
            <>
              {row.full_name} {!row.is_active && <Badge>inactive</Badge>}
            </>
          ),
        },
        {
          header: "Load limit",
          cell: (row) => (
            <span className="whitespace-nowrap tabular-nums">
              {row.max_daily_hours} h/day · {row.max_weekly_hours} h/week
            </span>
          ),
        },
        {
          header: "Qualified subjects",
          cell: (row, l) => {
            const codes = (row.qualified_subject_ids as number[])
              .map((id) => l.subjects?.find((s) => s.id === id)?.code)
              .filter(Boolean);
            return codes.length ? <span className="text-xs text-stone-700">{codes.join(", ")}</span> : "—";
          },
        },
        {
          header: "Slots marked",
          cell: (row) => {
            const slots = row.availability as Availability[];
            const blocked = slots.filter((slot) => slot.kind === "unavailable").length;
            const preferred = slots.length - blocked;
            return slots.length ? (
              <span className="whitespace-nowrap text-xs">
                {blocked} unavailable · {preferred} preferred
              </span>
            ) : (
              "—"
            );
          },
        },
      ]}
      fields={[
        { name: "employee_id", label: "Employee ID", type: "text", required: true },
        { name: "full_name", label: "Full name", type: "text", required: true },
        {
          name: "max_daily_hours",
          label: "Max teaching hours per day",
          type: "number",
          step: "0.5",
          nullable: true,
          hint: `Leave blank to use the school default (${dailyDefault}).`,
        },
        {
          name: "max_weekly_hours",
          label: "Max teaching hours per week",
          type: "number",
          step: "0.5",
          nullable: true,
          hint: `Leave blank to use the school default (${weeklyDefault}).`,
        },
        { name: "is_active", label: "Active (can be given classes)", type: "checkbox", full: true },
        {
          name: "qualified_subject_ids",
          label: "Qualified subjects",
          type: "multiselect",
          options: (l) => (l.subjects ?? []).map((s) => ({ value: s.id, label: `${s.code} – ${s.name}` })),
        },
        {
          name: "availability",
          label: "Unavailable and preferred time slots",
          type: "custom",
          render: (value, onChange, l) => (
            <AvailabilityGrid
              shifts={(l.shifts ?? []) as Shift[]}
              days={days}
              value={(value as Availability[]) ?? []}
              onChange={onChange}
            />
          ),
        },
      ]}
      defaults={{
        employee_id: "",
        full_name: "",
        max_daily_hours: "",
        max_weekly_hours: "",
        is_active: true,
        qualified_subject_ids: [],
        availability: [],
      }}
      searchText={(row) => `${row.employee_id} ${row.full_name}`}
    />
  );
}
