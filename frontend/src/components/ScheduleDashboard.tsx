"use client";

import Link from "next/link";

import type { Meter } from "@/lib/schedule";
import { conflictCounts, formatHours, percentOf, roomUsage, sectionProgress } from "@/lib/schedule";
import { useSchedule } from "@/lib/useSchedule";

import { Alert, Badge } from "./ui";

type Row = Meter & { flag?: string };

/** One measure per list, so every bar in a list shares one scale and one colour. */
function MeterList({ title, caption, rows, empty }: { title: string; caption: string; rows: Row[]; empty: string }) {
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h3 className="font-medium text-stone-900">{title}</h3>
      <p className="text-xs text-stone-500">{caption}</p>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-stone-500">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((row) => {
            const percent = percentOf(row.value, row.max);
            const text = `${formatHours(row.value)} of ${formatHours(row.max)}`;
            return (
              <li key={row.id} title={`${row.label}: ${text} (${percent}%)`}>
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate text-stone-800">
                    {row.label}
                    {row.flag && (
                      <span className="ml-2">
                        <Badge tone="amber">{row.flag}</Badge>
                      </span>
                    )}
                  </span>
                  <span className="whitespace-nowrap text-xs tabular-nums text-stone-600">
                    {text} · {percent}%
                  </span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded bg-stone-200" aria-hidden="true">
                  <div className="h-full rounded bg-emerald-600" style={{ width: `${percent}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Tile({ value, label, href, note }: { value: string; label: string; href: string; note?: string }) {
  return (
    <Link href={href} className="rounded-lg border border-stone-200 bg-white p-4 transition-colors hover:border-emerald-700">
      <p className="text-3xl font-semibold tabular-nums text-stone-900">{value}</p>
      <p className="mt-1 text-sm text-stone-600">{label}</p>
      {note && <p className="mt-1 text-xs text-stone-500">{note}</p>}
    </Link>
  );
}

export function ScheduleDashboard() {
  const { data, lookups, error } = useSchedule();
  if (error) return <Alert>{error}</Alert>;
  if (!data || !lookups) return <p className="text-sm text-stone-500">Loading the schedule summary…</p>;

  const required = data.assignments.reduce((sum, a) => sum + a.required_hours, 0);
  const placed = data.assignments.reduce((sum, a) => sum + Math.min(a.scheduled_hours, a.required_hours), 0);
  const unassigned = data.assignments.filter((a) => a.teacher_id === null).length;
  const teacherName = new Map(lookups.teachers.map((t) => [t.id, t.full_name]));
  const loads: Row[] = data.teacher_loads
    .filter((load) => load.assigned_hours > 0 || lookups.teachers.find((t) => t.id === load.teacher_id)?.is_active)
    .map((load) => ({
      id: load.teacher_id,
      label: teacherName.get(load.teacher_id) ?? "?",
      value: load.assigned_hours,
      max: load.max_weekly_hours,
      flag: load.status === "over" ? "Over limit" : load.issues.length ? "Check" : undefined,
    }))
    .sort((a, b) => b.value / (b.max || 1) - a.value / (a.max || 1));
  const attention = loads.filter((row) => row.flag).length;
  const sections = sectionProgress(data.assignments, lookups.sections);
  const rooms = roomUsage(data.entries, lookups.rooms, lookups.shifts, data.days).sort((a, b) => b.value - a.value);
  const conflicts = conflictCounts(data.conflicts);

  return (
    <section aria-label="Schedule summary" className="space-y-4">
      <h2 className="text-lg font-semibold text-stone-900">
        Schedule at a glance{" "}
        <span className="text-sm font-normal text-stone-500">
          {data.semester_number === 1 ? "1st" : "2nd"} semester
        </span>
      </h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          value={`${percentOf(placed, required)}%`}
          label="of class hours placed"
          note={`${formatHours(placed)} of ${formatHours(required)}`}
          href="/timetable"
        />
        <Tile value={String(data.summary.errors)} label={`conflict${data.summary.errors === 1 ? "" : "s"} to fix`} href="/timetable" />
        <Tile value={String(unassigned)} label="subjects without a teacher" href="/teacher-loading" />
        <Tile value={String(attention)} label={`teacher${attention === 1 ? "" : "s"} over limit or to check`} href="/teacher-loading" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <MeterList
          title="Sections"
          caption="Class hours on the timetable, of the hours each section must take."
          rows={sections}
          empty="No sections yet."
        />
        <MeterList
          title="Teacher load"
          caption="Hours assigned a week, of each teacher's weekly limit."
          rows={loads}
          empty="No teachers yet."
        />
        <MeterList
          title="Room use"
          caption="Hours in use a week, of the teaching hours in the school week."
          rows={rooms}
          empty="No rooms yet."
        />
        <section className="rounded-lg border border-stone-200 bg-white p-4">
          <h3 className="font-medium text-stone-900">Conflicts by kind</h3>
          <p className="text-xs text-stone-500">Open the timetable to see each one and its suggested fixes.</p>
          {conflicts.length === 0 ? (
            <p className="mt-3 text-sm text-stone-600">No conflicts and no subject short of hours.</p>
          ) : (
            <table className="mt-3 w-full text-sm">
              <tbody className="divide-y divide-stone-100">
                {conflicts.map((row) => (
                  <tr key={row.code}>
                    <th scope="row" className="py-1.5 text-left font-normal text-stone-800">
                      {row.label}
                    </th>
                    <td className="py-1.5 text-right">
                      <Badge tone={row.severity === "error" ? "amber" : "sky"}>
                        {row.severity === "error" ? "Conflict" : "To do"}
                      </Badge>
                    </td>
                    <td className="w-12 py-1.5 text-right font-medium tabular-nums">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </section>
  );
}
