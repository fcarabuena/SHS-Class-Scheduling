"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Field, inputClass, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SubstituteClass } from "@/lib/schedule";
import { formatHours } from "@/lib/schedule";
import { DAY_NAMES, shortTime } from "@/lib/types";
import { useSchedule } from "@/lib/useSchedule";

type Found = { key: string; classes: SubstituteClass[] };

export default function SubstitutesPage() {
  const { data, lookups, error } = useSchedule();
  const [teacherId, setTeacherId] = useState("");
  const [day, setDay] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [failed, setFailed] = useState("");

  const today = new Date().getDay(); // 1 = Monday, like the school days
  const chosenDay = day || (data?.days.includes(today) ? String(today) : String(data?.days[0] ?? 1));
  const key = `${teacherId}:${chosenDay}:${data?.semester_id}`;

  useEffect(() => {
    if (!teacherId || !data) return;
    let cancelled = false;
    const params = { teacher_id: teacherId, day_of_week: chosenDay, semester_id: data.semester_id };
    api<{ classes: SubstituteClass[] }>("/api/substitutes", { params })
      .then((result) => {
        if (cancelled) return;
        setFound({ key, classes: result.classes });
        setFailed("");
      })
      .catch((err) => !cancelled && setFailed(err instanceof ApiError ? err.message : "Could not look for substitutes."));
    return () => {
      cancelled = true;
    };
  }, [teacherId, chosenDay, data, key]);

  if (!data || !lookups) return error ? <Alert>{error}</Alert> : <Spinner />;

  const teachers = [...lookups.teachers].sort((a, b) => a.full_name.localeCompare(b.full_name));
  const teacherName = (id: number) => lookups.teachers.find((t) => t.id === id)?.full_name ?? "?";
  const periods = new Map(lookups.shifts.flatMap((shift) => shift.periods).map((period) => [period.id, period]));
  const current = found?.key === key ? found.classes : null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-stone-900">Find a substitute</h1>
        <p className="mt-1 max-w-2xl text-sm text-stone-600">
          When a teacher is absent, see who is free to cover each of their classes that day. Only teachers who are not
          teaching, not marked unavailable, and still within their daily limit are listed, best match first.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Absent teacher" className="w-64">
          {(id) => (
            <select id={id} className={inputClass} value={teacherId} onChange={(event) => setTeacherId(event.target.value)}>
              <option value="">Choose…</option>
              {teachers.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {teacher.full_name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Day" className="w-40">
          {(id) => (
            <select id={id} className={inputClass} value={chosenDay} onChange={(event) => setDay(event.target.value)}>
              {data.days.map((value) => (
                <option key={value} value={value}>
                  {DAY_NAMES[value]}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      {failed && <Alert>{failed}</Alert>}
      {!teacherId && <p className="text-sm text-stone-600">Choose the absent teacher to begin.</p>}
      {teacherId && !current && !failed && <Spinner label="Looking for free teachers…" />}
      {current && current.length === 0 && (
        <Alert kind="info">
          {teacherName(Number(teacherId))} has no classes on {DAY_NAMES[Number(chosenDay)]}.
        </Alert>
      )}

      {current?.map((item) => {
        const period = periods.get(item.period_id);
        const subject = lookups.subjects.find((s) => s.id === item.subject_id);
        const sections = item.section_ids.map((id) => lookups.sections.find((s) => s.id === id)?.name ?? "?").join(" + ");
        const room = lookups.rooms.find((r) => r.id === item.room_id)?.name ?? "no room";
        const heading = `${period?.name ?? ""} · ${subject?.code ?? "?"} · ${sections}`;
        return (
          <section key={item.entry_id} aria-label={heading} className="rounded-lg border border-stone-200 bg-white">
            <div className="border-b border-stone-200 px-4 py-3">
              <h2 className="font-medium text-stone-900">{heading}</h2>
              <p className="text-sm text-stone-600">
                {period ? `${shortTime(period.start_time)}–${shortTime(period.end_time)} · ` : ""}
                {subject?.name} · {room}
              </p>
            </div>
            {item.candidates.length === 0 ? (
              <p className="px-4 py-3 text-sm text-stone-600">
                Nobody is free at this time. Consider combining the class with another section or moving it.
              </p>
            ) : (
              <ol className="divide-y divide-stone-100">
                {item.candidates.map((candidate, index) => (
                  <li key={candidate.teacher_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
                    <span className="w-5 tabular-nums text-stone-500">{index + 1}.</span>
                    <span className="font-medium text-stone-900">{teacherName(candidate.teacher_id)}</span>
                    {candidate.qualified && <Badge tone="emerald">Qualified</Badge>}
                    {candidate.knows_section && <Badge tone="sky">Teaches this section</Badge>}
                    {candidate.notes.map((note) => (
                      <Badge key={note} tone="amber">
                        {note}
                      </Badge>
                    ))}
                    <span className="ml-auto whitespace-nowrap text-xs tabular-nums text-stone-600">
                      {formatHours(candidate.day_hours)} that day · {formatHours(candidate.week_hours)} that week, with this class
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        );
      })}
    </div>
  );
}
