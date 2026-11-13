"use client";

import { useEffect, useMemo, useState } from "react";

import { AutoScheduleDialog } from "@/components/AutoScheduleDialog";
import { Alert, Badge, Button, Field, inputClass, Spinner } from "@/components/ui";
import { api, ApiError, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CheckCell, Conflict, Entry, Fix, Meeting, Overview, Picked, ViewKind } from "@/lib/schedule";
import {
  assignmentsForView,
  cellKey,
  conflictsForView,
  entriesForView,
  formatHours,
  gridRows,
  meetingsByCell,
  remainingHours,
  severityByEntry,
} from "@/lib/schedule";
import { DAY_NAMES, labelOf, ROOM_TYPES, shortTime } from "@/lib/types";
import { semesterOptions, useSchedule } from "@/lib/useSchedule";

const VIEWS: { value: ViewKind; label: string; plural: string }[] = [
  { value: "section", label: "Section", plural: "sections" },
  { value: "teacher", label: "Teacher", plural: "teachers" },
  { value: "room", label: "Room", plural: "rooms" },
];

type Check = { key: string; cells: Map<string, CheckCell> };
type Advice = { entryId: number; conflicts: Conflict[]; fixes: Fix[] };

const pickedKey = (picked: Picked | null) => (picked ? `${picked.kind}:${picked.id}` : "");

export default function TimetablePage() {
  const { canEdit, user } = useAuth();
  const { data, lookups, error, setError, busy, run, semesterId, setSemesterId } = useSchedule();
  const [view, setView] = useState<ViewKind>(user?.teacher_id ? "teacher" : "section");
  const [chosenId, setChosenId] = useState<number | null>(user?.teacher_id ?? null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [hint, setHint] = useState("");
  const [exportAll, setExportAll] = useState(false);
  const [autoOpen, setAutoOpen] = useState(false);

  const names = useMemo(() => {
    const byId = <T extends { id: number }>(rows: T[] = []) => new Map(rows.map((row) => [row.id, row]));
    return {
      sections: byId(lookups?.sections),
      subjects: byId(lookups?.subjects),
      teachers: byId(lookups?.teachers),
      rooms: byId(lookups?.rooms),
    };
  }, [lookups]);

  const selectedId = picked?.kind === "entry" ? picked.id : null;

  // Real-time check: what would each slot lead to for the class in hand?
  useEffect(() => {
    if (!picked || !data || !canEdit) return;
    let cancelled = false;
    const body = picked.kind === "entry" ? { entry_id: picked.id } : { assignment_id: picked.id };
    api<{ cells: CheckCell[] }>("/api/schedule/check", { method: "POST", body })
      .then((result) => {
        if (cancelled) return;
        const cells = new Map(result.cells.map((cell) => [cellKey(cell.day_of_week, cell.period_id), cell]));
        setCheck({ key: pickedKey(picked), cells });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [picked, data, canEdit]);

  // Conflicts and suggested fixes of the selected class.
  useEffect(() => {
    if (selectedId === null || !data) return;
    let cancelled = false;
    api<{ conflicts: Conflict[]; fixes: Fix[] }>(`/api/schedule/entries/${selectedId}/suggestions`)
      .then((result) => {
        if (!cancelled) setAdvice({ entryId: selectedId, ...result });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selectedId, data]);

  if (!data || !lookups) return error ? <Alert>{error}</Alert> : <Spinner />;

  const options = {
    section: lookups.sections.map((s) => ({ id: s.id, label: s.name })),
    teacher: lookups.teachers
      .filter((t) => t.is_active || data.entries.some((e) => e.teacher_id === t.id))
      .map((t) => ({ id: t.id, label: t.full_name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    room: lookups.rooms.map((r) => ({ id: r.id, label: r.name })),
  }[view];
  const viewId = options.some((option) => option.id === chosenId) ? chosenId : (options[0]?.id ?? null);
  const viewInfo = VIEWS.find((v) => v.value === view)!;
  const viewLabel = options.find((option) => option.id === viewId)?.label ?? "";

  const section = view === "section" && viewId !== null ? names.sections.get(viewId) : undefined;
  const rows = gridRows(lookups.shifts, section ? section.shift_id : null);
  const multiShift = !section && lookups.shifts.length > 1;
  const visible = entriesForView(data.entries, view, viewId);
  const cells = meetingsByCell(visible);
  const severity = severityByEntry(data.conflicts);
  const palette = assignmentsForView(data.assignments, view, viewId).sort(
    (a, b) => remainingHours(b) - remainingHours(a) || a.id - b.id,
  );
  const listed = conflictsForView(data.conflicts, data.entries, view, viewId);
  const activeCheck = canEdit && picked && check?.key === pickedKey(picked) ? check.cells : null;
  const selected = selectedId === null ? undefined : data.entries.find((entry) => entry.id === selectedId);
  const selectedAdvice = advice && advice.entryId === selectedId ? advice : null;

  const sectionName = (id: number) => names.sections.get(id)?.name ?? "?";
  const subjectCode = (id: number) => names.subjects.get(id)?.code ?? "?";
  const teacherName = (id: number | null) => (id === null ? "No teacher" : (names.teachers.get(id)?.full_name ?? "?"));
  const roomName = (id: number | null) => (id === null ? "No room" : (names.rooms.get(id)?.name ?? "?"));
  const slotName = (entry: Entry) =>
    `${DAY_NAMES[entry.day_of_week]} ${rows.find((r) => r.period.id === entry.period_id)?.period.name ?? ""}`.trim();

  function switchView(next: ViewKind) {
    setView(next);
    setChosenId(null);
    setPicked(null);
    setHint("");
  }

  async function dropOn(day: number, periodId: number, item: Picked | null = picked) {
    if (!item || !canEdit || busy) return;
    const cell = activeCheck?.get(cellKey(day, periodId));
    setHint("");
    if (cell?.status === "current") return;
    if (cell?.status === "blocked") {
      setError(cell.messages[0] ?? "That slot cannot be used.");
      return;
    }
    if (item.kind === "assignment") {
      const body = {
        assignment_id: item.id,
        day_of_week: day,
        period_id: periodId,
        ...(view === "room" && viewId !== null ? { room_id: viewId } : {}),
      };
      const fresh = await run(() => api<Overview>("/api/schedule/entries", { method: "POST", body }));
      const left = fresh?.assignments.find((a) => a.id === item.id);
      // Keep the class in hand while it still has hours to place.
      if (!fresh || !left || remainingHours(left) === 0) setPicked(null);
    } else {
      await run(() =>
        api<Overview>(`/api/schedule/entries/${item.id}`, { method: "PUT", body: { day_of_week: day, period_id: periodId } }),
      );
    }
  }

  const updateEntry = (id: number, body: Record<string, unknown>) =>
    run(() => api<Overview>(`/api/schedule/entries/${id}`, { method: "PUT", body }));

  async function removeEntry(id: number) {
    if (await run(() => api<Overview>(`/api/schedule/entries/${id}`, { method: "DELETE" }))) setPicked(null);
  }

  function applyFix(entry: Entry, fix: Fix) {
    if (fix.kind === "move") return updateEntry(entry.id, { day_of_week: fix.day_of_week, period_id: fix.period_id });
    if (fix.kind === "room") return updateEntry(entry.id, { room_id: fix.room_id });
    const assignment = data!.assignments.find(
      (a) => a.section_id === entry.section_id && a.subject_id === entry.subject_id,
    );
    if (!assignment) return;
    return run(() =>
      api<Overview>(`/api/assignments/${assignment.id}`, { method: "PUT", body: { teacher_id: fix.teacher_id } }),
    );
  }

  async function exportAs(format: "xlsx" | "pdf") {
    const query = new URLSearchParams({ view, format, semester_id: String(data!.semester_id) });
    if (!exportAll && viewId !== null) query.set("id", String(viewId));
    const name = exportAll ? `all-${viewInfo.plural}` : viewLabel.replace(/[^\w-]+/g, "-");
    try {
      await download(`/api/schedule/export?${query}`, `timetable-${name}.${format}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The export failed.");
    }
  }

  function cardLines(meeting: Meeting): string[] {
    const first = meeting.entries[0];
    const sections = meeting.entries.map((entry) => sectionName(entry.section_id)).join(" + ");
    if (view === "section") {
      const others = meeting.entries.length > 1 ? [`with ${meeting.entries.length - 1} more section(s)`] : [];
      return [teacherName(first.teacher_id), roomName(first.room_id), ...others];
    }
    return [sections, view === "teacher" ? roomName(first.room_id) : teacherName(first.teacher_id)];
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.75rem] font-normal leading-tight text-stone-900">Timetable</h1>
          <p className="mt-1 max-w-2xl text-sm text-stone-600">
            {canEdit
              ? "Drag a class onto the week, or click a class and then a slot. Green slots are free of conflicts; red slots would cause one."
              : "Weekly class schedule by section, teacher or room."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={data.summary.errors ? "amber" : "emerald"}>
            {data.summary.errors} conflict{data.summary.errors === 1 ? "" : "s"}
          </Badge>
          <Badge tone={data.summary.incomplete ? "sky" : "emerald"}>{data.summary.incomplete} subjects short of hours</Badge>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 print:hidden">
        <div role="group" aria-label="View by" className="flex overflow-hidden rounded-md border border-stone-300">
          {VIEWS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={view === item.value}
              className={`px-3 py-2 text-sm font-medium ${
                view === item.value ? "bg-emerald-800 text-white" : "bg-white text-stone-700 hover:bg-stone-100"
              }`}
              onClick={() => switchView(item.value)}
            >
              By {item.label.toLowerCase()}
            </button>
          ))}
        </div>
        <Field label={viewInfo.label} className="w-60">
          {(id) => (
            <select
              id={id}
              className={inputClass}
              value={viewId ?? ""}
              onChange={(event) => {
                setChosenId(Number(event.target.value));
                setPicked(null);
              }}
            >
              {options.length === 0 && <option value="">None yet</option>}
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Semester" className="w-60">
          {(id) => (
            <select
              id={id}
              className={inputClass}
              value={semesterId ?? ""}
              onChange={(event) => {
                setPicked(null);
                setSemesterId(Number(event.target.value));
              }}
            >
              {semesterOptions(lookups.years).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {canEdit && (
            <Button
              onClick={() => {
                setPicked(null);
                setAutoOpen(true);
              }}
            >
              Auto-schedule
            </Button>
          )}
          <label className="flex items-center gap-2 text-sm text-stone-700">
            <input type="checkbox" checked={exportAll} onChange={(event) => setExportAll(event.target.checked)} />
            All {viewInfo.plural}
          </label>
          <Button variant="secondary" onClick={() => exportAs("xlsx")}>
            Export Excel
          </Button>
          <Button variant="secondary" onClick={() => exportAs("pdf")}>
            Export PDF
          </Button>
        </div>
      </div>

      {error && <Alert>{error}</Alert>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0 space-y-2">
          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="w-full min-w-[38rem] table-fixed border-collapse text-sm">
              <caption className="sr-only">
                Weekly timetable of {viewLabel}
              </caption>
              <thead>
                <tr className="bg-stone-100 text-stone-700">
                  <th scope="col" className="w-24 border-b border-r border-stone-200 px-2 py-2 text-left font-medium">
                    Period
                  </th>
                  {data.days.map((day) => (
                    <th key={day} scope="col" className="border-b border-r border-stone-200 px-2 py-2 font-medium last:border-r-0">
                      {DAY_NAMES[day]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(({ period, shiftName }) => (
                  <tr key={period.id} className={period.is_break ? "bg-stone-50 text-stone-500" : ""}>
                    <th scope="row" className="border-b border-r border-stone-200 px-2 py-1.5 text-left align-top font-normal">
                      <span className="block font-medium text-stone-800">{period.name}</span>
                      <span className="block text-xs tabular-nums text-stone-500">
                        {shortTime(period.start_time)}–{shortTime(period.end_time)}
                      </span>
                      {multiShift && <span className="block text-xs text-stone-500">{shiftName}</span>}
                    </th>
                    {period.is_break ? (
                      <td colSpan={data.days.length} className="border-b border-stone-200 px-2 py-1 text-center text-xs italic">
                        Break
                      </td>
                    ) : (
                      data.days.map((day) => {
                        const key = cellKey(day, period.id);
                        const meetings = cells.get(key) ?? [];
                        const state = activeCheck?.get(key);
                        const tone =
                          !picked || !state
                            ? picked && activeCheck
                              ? "bg-stone-100"
                              : ""
                            : state.status === "ok"
                              ? "bg-emerald-50 outline-dashed outline-1 -outline-offset-2 outline-emerald-500"
                              : state.status === "conflict"
                                ? "bg-red-50 outline-dashed outline-1 -outline-offset-2 outline-red-400"
                                : state.status === "blocked"
                                  ? "bg-stone-200"
                                  : "bg-sky-50";
                        // Until the check answers, any slot accepts a drop; the server still validates it.
                        const droppable = canEdit && !!picked && (activeCheck ? !!state && state.status !== "blocked" : true);
                        const label = `${DAY_NAMES[day]} ${period.name}`;
                        return (
                          <td
                            key={day}
                            data-cell={key}
                            data-status={state?.status}
                            title={state?.messages.join("\n")}
                            className={`h-16 border-b border-r border-stone-200 p-1 align-top last:border-r-0 ${tone}`}
                            onDragOver={(event) => {
                              if (!droppable) return;
                              event.preventDefault();
                              const message = state?.messages[0] ?? (state?.swap ? "Swap with the class here." : "");
                              if (message !== hint) setHint(message ? `${label}: ${message}` : "");
                            }}
                            onDrop={(event) => {
                              event.preventDefault();
                              dropOn(day, period.id);
                            }}
                          >
                            <div className="flex flex-col gap-1">
                              {meetings.map((meeting) => {
                                const first = meeting.entries[0];
                                const hasError = meeting.entries.some((entry) => severity.has(entry.id));
                                const isSelected = meeting.entries.some((entry) => entry.id === selectedId);
                                return (
                                  <button
                                    key={meeting.key}
                                    type="button"
                                    draggable={canEdit && !first.pinned}
                                    aria-pressed={isSelected}
                                    aria-label={`${subjectCode(first.subject_id)}, ${label}${hasError ? ", has a conflict" : ""}${first.pinned ? ", pinned" : ""}`}
                                    className={`w-full rounded border px-1.5 py-1 text-left text-xs leading-tight ${
                                      hasError ? "border-red-400 bg-red-100 text-red-950" : "border-emerald-300 bg-emerald-100 text-emerald-950"
                                    } ${isSelected ? "ring-2 ring-emerald-800" : ""} ${canEdit && !first.pinned ? "cursor-grab" : ""}`}
                                    onClick={() => setPicked(isSelected ? null : { kind: "entry", id: first.id })}
                                    onDragStart={(event) => {
                                      event.dataTransfer.setData("text/plain", String(first.id));
                                      event.dataTransfer.effectAllowed = "move";
                                      setPicked({ kind: "entry", id: first.id });
                                    }}
                                    onDragEnd={() => setHint("")}
                                  >
                                    <span className="block truncate font-semibold">
                                      {subjectCode(first.subject_id)}
                                      {first.pinned && <span className="ml-1 font-normal">(pinned)</span>}
                                    </span>
                                    {cardLines(meeting).map((line) => (
                                      <span key={line} className="block truncate">
                                        {line}
                                      </span>
                                    ))}
                                  </button>
                                );
                              })}
                              {meetings.length === 0 && droppable && state && (
                                <button
                                  type="button"
                                  className="h-12 w-full rounded text-xs text-stone-500 hover:bg-white/70"
                                  aria-label={`${label}: ${state.status === "conflict" ? "place here despite a conflict" : "place here"}`}
                                  onClick={() => dropOn(day, period.id)}
                                >
                                  {state.status === "conflict" ? "Conflict" : "Place here"}
                                </button>
                              )}
                            </div>
                          </td>
                        );
                      })
                    )}
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={data.days.length + 1} className="px-3 py-8 text-center text-stone-500">
                      No bell schedule yet. Set one up in School setup.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p role="status" className="min-h-5 text-sm text-red-800">
            {hint}
          </p>

          <section aria-label="Conflicts">
            <h2 className="mb-2 text-lg font-semibold text-stone-900">
              Conflicts for {viewLabel || "this view"} <span className="font-normal text-stone-500">({listed.length})</span>
            </h2>
            {listed.length === 0 ? (
              <p className="text-sm text-stone-600">No conflicts here.</p>
            ) : (
              <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
                {listed.map((conflict) => (
                  <li key={conflict.key} className="flex items-start gap-2 px-3 py-2 text-sm">
                    <Badge tone={conflict.severity === "error" ? "amber" : "sky"}>
                      {conflict.severity === "error" ? "Conflict" : "Short"}
                    </Badge>
                    <span className="flex-1">{conflict.message}</span>
                    {conflict.severity === "error" && conflict.entry_ids.length > 0 && (
                      <Button variant="ghost" small onClick={() => setPicked({ kind: "entry", id: conflict.entry_ids[0] })}>
                        Show fixes
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside className="space-y-5 print:hidden">
          {selected && (
            <section aria-label="Selected class" className="rounded-lg border border-emerald-700 bg-white p-3">
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-base font-semibold text-stone-900">
                  {subjectCode(selected.subject_id)} · {sectionName(selected.section_id)}
                </h2>
                <Button variant="ghost" small aria-label="Close selected class" onClick={() => setPicked(null)}>
                  ✕
                </Button>
              </div>
              <p className="text-sm text-stone-600">{names.subjects.get(selected.subject_id)?.name}</p>
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex gap-2">
                  <dt className="w-16 text-stone-500">When</dt>
                  <dd>{slotName(selected)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-16 text-stone-500">Teacher</dt>
                  <dd>{teacherName(selected.teacher_id)}</dd>
                </div>
                {selected.combined_group_id !== null && (
                  <div className="flex gap-2">
                    <dt className="w-16 text-stone-500">Combined</dt>
                    <dd>
                      {data.entries
                        .filter(
                          (e) =>
                            e.combined_group_id === selected.combined_group_id &&
                            e.day_of_week === selected.day_of_week &&
                            e.period_id === selected.period_id,
                        )
                        .map((e) => sectionName(e.section_id))
                        .join(" + ")}
                    </dd>
                  </div>
                )}
              </dl>
              {canEdit ? (
                <div className="mt-3 space-y-3">
                  <Field label="Room">
                    {(id) => (
                      <select
                        id={id}
                        className={inputClass}
                        value={selected.room_id ?? ""}
                        disabled={busy || selected.pinned}
                        onChange={(event) =>
                          updateEntry(selected.id, { room_id: event.target.value ? Number(event.target.value) : null })
                        }
                      >
                        <option value="">No room</option>
                        {lookups.rooms.map((room) => (
                          <option key={room.id} value={room.id}>
                            {room.name} ({labelOf(ROOM_TYPES, room.type)}, {room.capacity})
                          </option>
                        ))}
                      </select>
                    )}
                  </Field>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.pinned}
                      disabled={busy}
                      onChange={(event) => updateEntry(selected.id, { pinned: event.target.checked })}
                    />
                    Pinned (cannot be moved or removed)
                  </label>
                  <Button variant="danger" small disabled={busy || selected.pinned} onClick={() => removeEntry(selected.id)}>
                    Remove from timetable
                  </Button>
                </div>
              ) : (
                <p className="mt-2 text-sm">Room: {roomName(selected.room_id)}</p>
              )}

              {selectedAdvice && selectedAdvice.conflicts.length > 0 && (
                <div className="mt-4 border-t border-stone-200 pt-3">
                  <h3 className="text-sm font-semibold text-stone-900">Problems with this class</h3>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-800">
                    {selectedAdvice.conflicts.map((conflict) => (
                      <li key={conflict.key}>{conflict.message}</li>
                    ))}
                  </ul>
                  {canEdit && selectedAdvice.fixes.length > 0 && (
                    <>
                      <h3 className="mt-3 text-sm font-semibold text-stone-900">Suggested fixes</h3>
                      <ul className="mt-1 space-y-1">
                        {selectedAdvice.fixes.map((fix) => (
                          <li key={`${fix.kind}:${fix.label}`}>
                            <Button
                              variant="secondary"
                              small
                              className="w-full justify-between"
                              disabled={busy}
                              onClick={() => applyFix(selected, fix)}
                            >
                              <span className="text-left">{fix.label}</span>
                              <span className="whitespace-nowrap text-xs font-normal text-stone-500">
                                {fix.remaining_errors === 0 ? "clears all conflicts" : `${fix.remaining_errors} left`}
                              </span>
                            </Button>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {canEdit && selectedAdvice.fixes.length === 0 && selectedAdvice.conflicts.some((c) => c.severity === "error") && (
                    <p className="mt-2 text-sm text-stone-600">
                      No single change clears this{selected.pinned ? " while the class is pinned" : ""}. Try moving another class first.
                    </p>
                  )}
                </div>
              )}
            </section>
          )}

          {view !== "room" && (
            <section aria-label="Classes to place">
              <h2 className="text-lg font-semibold text-stone-900">Classes to place</h2>
              <p className="mb-2 text-xs text-stone-600">
                {canEdit ? "Drag onto the week, or click one and then click a slot." : "Hours still to be scheduled."}
              </p>
              <ul className="space-y-1.5">
                {palette.map((assignment) => {
                  const left = remainingHours(assignment);
                  const isPicked = picked?.kind === "assignment" && picked.id === assignment.id;
                  const detail = view === "section" ? teacherName(assignment.teacher_id) : sectionName(assignment.section_id);
                  const title = `${subjectCode(assignment.subject_id)} · ${detail}`;
                  return (
                    <li key={assignment.id}>
                      <button
                        type="button"
                        draggable={canEdit}
                        disabled={!canEdit}
                        aria-pressed={isPicked}
                        aria-label={`${title}, ${formatHours(left)} left to place`}
                        className={`flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm ${
                          isPicked ? "border-emerald-800 bg-emerald-100 ring-1 ring-emerald-800" : "border-stone-200 bg-white"
                        } ${left === 0 ? "text-stone-400" : "text-stone-900"} ${canEdit ? "cursor-grab hover:border-emerald-700" : ""}`}
                        onClick={() => setPicked(isPicked ? null : { kind: "assignment", id: assignment.id })}
                        onDragStart={(event) => {
                          event.dataTransfer.setData("text/plain", String(assignment.id));
                          event.dataTransfer.effectAllowed = "copy";
                          setPicked({ kind: "assignment", id: assignment.id });
                        }}
                        onDragEnd={() => {
                          setHint("");
                          setPicked((current) => (current?.kind === "assignment" ? null : current));
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{subjectCode(assignment.subject_id)}</span>
                          <span className="block truncate text-xs text-stone-500">
                            {detail}
                            {assignment.combined_group_id !== null && " · combined"}
                          </span>
                        </span>
                        <span className="whitespace-nowrap text-xs tabular-nums">
                          {left === 0 ? "done" : `${formatHours(left)} left`}
                        </span>
                      </button>
                    </li>
                  );
                })}
                {palette.length === 0 && (
                  <li className="text-sm text-stone-500">
                    Nothing assigned yet. Add subjects and teachers on the Teacher loading page.
                  </li>
                )}
              </ul>
            </section>
          )}
        </aside>
      </div>

      {autoOpen && (
        <AutoScheduleDialog
          semesterId={data.semester_id}
          onApplied={(fresh) => run(async () => fresh)}
          onClose={() => setAutoOpen(false)}
        />
      )}
    </div>
  );
}
