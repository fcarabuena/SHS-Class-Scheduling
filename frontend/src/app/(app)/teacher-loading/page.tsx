"use client";

import { useMemo, useState } from "react";

import { Alert, Badge, Button, Field, inputClass, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Assignment, Overview, TeacherLoad } from "@/lib/schedule";
import { formatHours, loadPercent, teacherChoices } from "@/lib/schedule";
import { semesterOptions, useSchedule } from "@/lib/useSchedule";

const BAR = { ok: "bg-emerald-600", full: "bg-amber-500", over: "bg-red-600" };

export default function TeacherLoadingPage() {
  const { canEdit } = useAuth();
  const { data, lookups, error, busy, run, semesterId, setSemesterId } = useSchedule();
  const [sectionFilter, setSectionFilter] = useState("");
  const [onlyUnassigned, setOnlyUnassigned] = useState(false);
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState(false);
  const [combining, setCombining] = useState<Assignment | null>(null);

  const names = useMemo(() => {
    const byId = <T extends { id: number }>(rows: T[] = []) => new Map(rows.map((row) => [row.id, row]));
    return {
      sections: byId(lookups?.sections),
      subjects: byId(lookups?.subjects),
      teachers: byId(lookups?.teachers),
    };
  }, [lookups]);

  if (!data || !lookups) return error ? <Alert>{error}</Alert> : <Spinner />;

  const loads = new Map(data.teacher_loads.map((load) => [load.teacher_id, load]));
  const sectionName = (id: number) => names.sections.get(id)?.name ?? "?";
  const rows = data.assignments
    .filter((a) => !sectionFilter || a.section_id === Number(sectionFilter))
    .filter((a) => !onlyUnassigned || a.teacher_id === null)
    .sort(
      (a, b) =>
        sectionName(a.section_id).localeCompare(sectionName(b.section_id)) ||
        (names.subjects.get(a.subject_id)?.code ?? "").localeCompare(names.subjects.get(b.subject_id)?.code ?? ""),
    );
  const unassigned = data.assignments.filter((a) => a.teacher_id === null).length;
  const overloaded = data.teacher_loads.filter((load) => load.status === "over" || load.issues.length > 0).length;

  const change = (path: string, method: "POST" | "PUT" | "DELETE", body?: unknown) =>
    run(() => api<Overview>(path, { method, body }));

  async function generate() {
    setNotice("");
    const result = await run(() =>
      api<Overview & { created: number }>("/api/assignments/generate", { method: "POST", body: { semester_id: data!.semester_id } }),
    );
    if (result) {
      setNotice(
        result.created
          ? `Added ${result.created} subject${result.created === 1 ? "" : "s"} from the curriculum.`
          : "Every section already has the subjects its curriculum requires.",
      );
    }
  }

  async function autoAssign() {
    setNotice("");
    const result = await run(() =>
      api<Overview & { assigned: number; left: number }>("/api/assignments/auto-assign", {
        method: "POST",
        body: { semester_id: data!.semester_id },
      }),
    );
    if (result) {
      setNotice(
        `Assigned a teacher to ${result.assigned} subject${result.assigned === 1 ? "" : "s"}.` +
          (result.left
            ? ` ${result.left} still need one: no qualified teacher has room left. Add qualifications or teachers, or raise a limit.`
            : ""),
      );
    }
  }

  function partners(assignment: Assignment): string {
    return data!.assignments
      .filter((a) => a.combined_group_id === assignment.combined_group_id && a.id !== assignment.id)
      .map((a) => sectionName(a.section_id))
      .join(", ");
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.75rem] font-normal leading-tight text-stone-900">Teacher loading</h1>
          <p className="mt-1 max-w-2xl text-sm text-stone-600">
            Decide who teaches each subject to each section. Loads are checked against every teacher&apos;s daily and
            weekly limits as you assign.
          </p>
        </div>
        <Field label="Semester" className="w-64">
          {(id) => (
            <select
              id={id}
              className={inputClass}
              value={semesterId ?? ""}
              onChange={(event) => setSemesterId(Number(event.target.value))}
            >
              {semesterOptions(lookups.years).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={unassigned ? "amber" : "emerald"}>
          {unassigned} of {data.assignments.length} without a teacher
        </Badge>
        <Badge tone={overloaded ? "amber" : "emerald"}>
          {overloaded} teacher{overloaded === 1 ? " needs" : "s need"} attention
        </Badge>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_17rem]">
        <section aria-label="Subjects and teachers" className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Section" className="w-56">
              {(id) => (
                <select id={id} className={inputClass} value={sectionFilter} onChange={(e) => setSectionFilter(e.target.value)}>
                  <option value="">All sections</option>
                  {lookups.sections.map((section) => (
                    <option key={section.id} value={section.id}>
                      {section.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm text-stone-700">
              <input type="checkbox" checked={onlyUnassigned} onChange={(e) => setOnlyUnassigned(e.target.checked)} />
              Only without a teacher
            </label>
            {canEdit && (
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="secondary" disabled={busy} onClick={generate}>
                  Add subjects from curriculum
                </Button>
                <Button variant="secondary" disabled={busy || unassigned === 0} onClick={autoAssign}>
                  Auto-assign teachers
                </Button>
                <Button disabled={busy} onClick={() => setAdding(true)}>
                  Add subject
                </Button>
              </div>
            )}
          </div>

          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="w-full min-w-[38rem] text-sm">
              <thead className="bg-stone-100 text-left text-xs uppercase tracking-wide text-stone-600">
                <tr>
                  <th scope="col" className="px-3 py-2">Section</th>
                  <th scope="col" className="px-3 py-2">Subject</th>
                  <th scope="col" className="px-3 py-2">Hours / week</th>
                  <th scope="col" className="px-3 py-2">Teacher</th>
                  {canEdit && <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {rows.map((assignment) => {
                  const subject = names.subjects.get(assignment.subject_id);
                  const teacher = assignment.teacher_id === null ? undefined : names.teachers.get(assignment.teacher_id);
                  const choices = teacherChoices(lookups.teachers, assignment.subject_id);
                  const unqualified = teacher && !teacher.qualified_subject_ids.includes(assignment.subject_id);
                  const label = `${sectionName(assignment.section_id)} ${subject?.code ?? ""}`;
                  const option = (t: (typeof lookups.teachers)[number]) => {
                    const load = loads.get(t.id);
                    return (
                      <option key={t.id} value={t.id}>
                        {t.full_name}
                        {load ? ` (${formatHours(load.assigned_hours)} of ${formatHours(load.max_weekly_hours)})` : ""}
                      </option>
                    );
                  };
                  return (
                    <tr key={assignment.id}>
                      <td className="whitespace-nowrap px-3 py-2 font-medium">{sectionName(assignment.section_id)}</td>
                      <td className="px-3 py-2">
                        <span className="font-medium">{subject?.code}</span>{" "}
                        <span className="text-stone-600">{subject?.name}</span>
                        {assignment.combined_group_id !== null && (
                          <span className="ml-2">
                            <Badge tone="sky">Combined with {partners(assignment)}</Badge>
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                        {formatHours(assignment.required_hours)}
                        <span className="text-xs text-stone-500"> · {formatHours(assignment.scheduled_hours)} placed</span>
                      </td>
                      <td className="px-3 py-2">
                        {canEdit ? (
                          <select
                            aria-label={`Teacher for ${label}`}
                            className={`${inputClass} min-w-40 ${unqualified ? "border-amber-500" : ""}`}
                            value={assignment.teacher_id ?? ""}
                            disabled={busy}
                            onChange={(event) =>
                              change(`/api/assignments/${assignment.id}`, "PUT", {
                                teacher_id: event.target.value ? Number(event.target.value) : null,
                              })
                            }
                          >
                            <option value="">No teacher yet</option>
                            <optgroup label="Qualified">{choices.qualified.map(option)}</optgroup>
                            <optgroup label="Not qualified for this subject">{choices.others.map(option)}</optgroup>
                          </select>
                        ) : (
                          (teacher?.full_name ?? <span className="text-stone-500">No teacher yet</span>)
                        )}
                        {unqualified && <p className="mt-1 text-xs text-amber-800">Not qualified for this subject.</p>}
                      </td>
                      {canEdit && (
                        <td className="whitespace-nowrap px-3 py-2 text-right">
                          {assignment.combined_group_id === null ? (
                            <Button variant="ghost" small disabled={busy} onClick={() => setCombining(assignment)}>
                              Combine
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              small
                              disabled={busy}
                              onClick={() => change(`/api/assignments/${assignment.id}/separate`, "POST")}
                            >
                              Separate
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            small
                            disabled={busy}
                            aria-label={`Remove ${label}`}
                            onClick={() => {
                              const placed = assignment.scheduled_hours > 0 ? " Its classes on the timetable are removed too." : "";
                              if (window.confirm(`Remove ${label}?${placed}`)) change(`/api/assignments/${assignment.id}`, "DELETE");
                            }}
                          >
                            Remove
                          </Button>
                        </td>
                      )}
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-3 py-8 text-center text-stone-500">
                      {data.assignments.length === 0
                        ? "No subjects yet. Use “Add subjects from curriculum” to fill in what each section must take."
                        : "Nothing matches the filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section aria-label="Teacher loads" className="min-w-0">
          <h2 className="mb-3 text-lg font-semibold text-stone-900">Teacher loads</h2>
          <ul className="space-y-2">
            {[...lookups.teachers]
              .filter((teacher) => teacher.is_active || (loads.get(teacher.id)?.assigned_hours ?? 0) > 0)
              .sort((a, b) => a.full_name.localeCompare(b.full_name))
              .map((teacher) => {
                const load = loads.get(teacher.id);
                return load ? <LoadCard key={teacher.id} name={teacher.full_name} load={load} /> : null;
              })}
            {lookups.teachers.length === 0 && <li className="text-sm text-stone-500">No teachers yet.</li>}
          </ul>
        </section>
      </div>

      {adding && (
        <AddDialog
          data={data}
          sections={lookups.sections}
          subjects={lookups.subjects}
          defaultSection={sectionFilter}
          onClose={() => setAdding(false)}
          onSave={async (body) => {
            if (await change("/api/assignments", "POST", body)) setAdding(false);
          }}
        />
      )}

      {combining && (
        <CombineDialog
          assignment={combining}
          candidates={data.assignments.filter(
            (a) =>
              a.id !== combining.id &&
              a.subject_id === combining.subject_id &&
              names.sections.get(a.section_id)?.shift_id === names.sections.get(combining.section_id)?.shift_id,
          )}
          sectionName={sectionName}
          subjectCode={names.subjects.get(combining.subject_id)?.code ?? ""}
          onClose={() => setCombining(null)}
          onSave={async (ids) => {
            if (await change("/api/assignments/combine", "POST", { assignment_ids: [combining.id, ...ids] })) setCombining(null);
          }}
        />
      )}
    </div>
  );
}

function LoadCard({ name, load }: { name: string; load: TeacherLoad }) {
  const attention = load.status === "over" || load.issues.length > 0;
  return (
    <li className={`rounded-lg border bg-white p-3 ${attention ? "border-amber-400" : "border-stone-200"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm font-medium text-stone-900">{name}</span>
        <span className="whitespace-nowrap text-sm tabular-nums text-stone-700">
          {formatHours(load.assigned_hours)} of {formatHours(load.max_weekly_hours)}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`Weekly load of ${name}`}
        aria-valuemin={0}
        aria-valuemax={load.max_weekly_hours}
        aria-valuenow={load.assigned_hours}
        className="mt-2 h-2 overflow-hidden rounded bg-stone-200"
      >
        <div className={`h-full ${BAR[load.status]}`} style={{ width: `${loadPercent(load)}%` }} />
      </div>
      <p className="mt-1 text-xs text-stone-500">
        Limit {formatHours(load.max_daily_hours)} a day · {formatHours(load.scheduled_hours)} on the timetable
      </p>
      {load.issues.map((issue) => (
        <p key={issue} className="mt-1 text-xs font-medium text-amber-900">
          {issue}
        </p>
      ))}
    </li>
  );
}

type AddProps = {
  data: Overview;
  sections: { id: number; name: string }[];
  subjects: { id: number; code: string; name: string }[];
  defaultSection: string;
  onClose: () => void;
  onSave: (body: { semester_id: number; section_id: number; subject_id: number }) => void;
};

function AddDialog({ data, sections, subjects, defaultSection, onClose, onSave }: AddProps) {
  const [sectionId, setSectionId] = useState(defaultSection);
  const [subjectId, setSubjectId] = useState("");
  const taken = new Set(data.assignments.filter((a) => a.section_id === Number(sectionId)).map((a) => a.subject_id));
  return (
    <Modal title="Add a subject to a section" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({ semester_id: data.semester_id, section_id: Number(sectionId), subject_id: Number(subjectId) });
        }}
      >
        <Field label="Section" required>
          {(id) => (
            <select id={id} className={inputClass} required value={sectionId} onChange={(e) => setSectionId(e.target.value)}>
              <option value="">Choose…</option>
              {sections.map((section) => (
                <option key={section.id} value={section.id}>
                  {section.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Subject" required hint="Subjects the section already has are not listed.">
          {(id) => (
            <select id={id} className={inputClass} required value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
              <option value="">Choose…</option>
              {subjects
                .filter((subject) => !taken.has(subject.id))
                .map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.code} – {subject.name}
                  </option>
                ))}
            </select>
          )}
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Add</Button>
        </div>
      </form>
    </Modal>
  );
}

type CombineProps = {
  assignment: Assignment;
  candidates: Assignment[];
  sectionName: (id: number) => string;
  subjectCode: string;
  onClose: () => void;
  onSave: (ids: number[]) => void;
};

function CombineDialog({ assignment, candidates, sectionName, subjectCode, onClose, onSave }: CombineProps) {
  const [chosen, setChosen] = useState<number[]>([]);
  return (
    <Modal title={`Combine ${subjectCode} for ${sectionName(assignment.section_id)}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-stone-600">
          Combined sections are taught together: one teacher, one room, one slot on the timetable, counted once in the
          teacher&apos;s load. Only sections in the same shift that take {subjectCode} can be combined.
        </p>
        {candidates.length === 0 ? (
          <Alert kind="info">No other section in this shift takes {subjectCode} this semester.</Alert>
        ) : (
          <ul className="space-y-1">
            {candidates.map((candidate) => (
              <li key={candidate.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={chosen.includes(candidate.id)}
                    onChange={(event) =>
                      setChosen((current) =>
                        event.target.checked ? [...current, candidate.id] : current.filter((id) => id !== candidate.id),
                      )
                    }
                  />
                  {sectionName(candidate.section_id)}
                  {candidate.combined_group_id !== null && <Badge tone="sky">already combined</Badge>}
                </label>
              </li>
            ))}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={chosen.length === 0} onClick={() => onSave(chosen)}>
            Combine sections
          </Button>
        </div>
      </div>
    </Modal>
  );
}
