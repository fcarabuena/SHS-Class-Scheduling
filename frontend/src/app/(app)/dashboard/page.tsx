"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ScheduleDashboard } from "@/components/ScheduleDashboard";
import { Alert, Badge, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Row, SchoolYear, Shift } from "@/lib/types";
import { shortTime } from "@/lib/types";

const COUNTS = [
  { key: "strands", label: "Strands", href: "/strands" },
  { key: "subjects", label: "Subjects", href: "/subjects" },
  { key: "sections", label: "Sections", href: "/sections" },
  { key: "teachers", label: "Teachers", href: "/teachers" },
  { key: "rooms", label: "Rooms", href: "/rooms" },
];

type Data = { counts: Record<string, number>; years: SchoolYear[]; shifts: Shift[] };

export default function DashboardPage() {
  const { school, user } = useAuth();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [years, shifts, ...lists] = await Promise.all([
          api<SchoolYear[]>("/api/school-years"),
          api<Shift[]>("/api/shifts"),
          ...COUNTS.map((item) => api<Row[]>(`/api/${item.key}`)),
        ]);
        if (cancelled) return;
        const counts = Object.fromEntries(COUNTS.map((item, index) => [item.key, lists[index].length]));
        setData({ counts, years, shifts });
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the dashboard.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;

  const activeYear = data.years.find((year) => year.is_active);
  const activeSemester = activeYear?.semesters.find((semester) => semester.is_active);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[1.75rem] font-normal leading-tight text-stone-900">{school?.name}</h1>
        <p className="mt-1 text-sm text-stone-600">
          Signed in as {user?.full_name}.{" "}
          {activeYear ? (
            <>
              School year <strong>{activeYear.name}</strong>
              {activeSemester && (
                <>
                  , {activeSemester.number === 1 ? "1st" : "2nd"} semester ({activeSemester.start_date} to{" "}
                  {activeSemester.end_date})
                </>
              )}
              .
            </>
          ) : (
            "No active school year yet."
          )}
        </p>
      </div>

      <section aria-label="Record counts" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {COUNTS.map((item) => (
          <Link
            key={item.key}
            href={item.href}
            className="rounded-lg border border-stone-200 bg-white p-4 transition-colors hover:border-emerald-700"
          >
            <p className="text-3xl font-semibold tabular-nums text-stone-900">{data.counts[item.key]}</p>
            <p className="mt-1 text-sm text-stone-600">{item.label}</p>
          </Link>
        ))}
      </section>

      {activeYear && <ScheduleDashboard />}

      <section>
        <h2 className="mb-3 text-lg font-semibold text-stone-900">Shifts and bell schedule</h2>
        {data.shifts.length === 0 && <p className="text-sm text-stone-600">No shifts have been set up.</p>}
        <div className="grid gap-4 lg:grid-cols-2">
          {data.shifts.map((shift) => (
            <div key={shift.id} className="rounded-lg border border-stone-200 bg-white p-4">
              <p className="font-medium text-stone-900">
                {shift.name}{" "}
                <span className="font-normal text-stone-500">
                  {shortTime(shift.start_time)}–{shortTime(shift.end_time)}
                </span>
              </p>
              <ul className="mt-3 space-y-1 text-sm">
                {shift.periods.map((period) => (
                  <li key={period.id} className="flex items-center justify-between gap-3">
                    <span className={period.is_break ? "text-stone-500" : "text-stone-800"}>
                      {period.name} {period.is_break && <Badge tone="amber">break</Badge>}
                    </span>
                    <span className="tabular-nums text-stone-600">
                      {shortTime(period.start_time)}–{shortTime(period.end_time)}
                    </span>
                  </li>
                ))}
                {shift.periods.length === 0 && <li className="text-stone-500">No periods yet.</li>}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
