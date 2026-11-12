"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Alert, Badge, Button, inputClass, Spinner, TextField } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { generateBellSchedule, type PeriodRow, validateBellSchedule } from "@/lib/bell";
import type { School, SchoolYear, Shift } from "@/lib/types";
import { shortTime } from "@/lib/types";

const STEPS = ["School", "School year", "Shifts", "Bell schedule", "Strands"];

type StepProps = { onNext: () => void; onBack?: () => void };

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function StepActions({ onBack, nextLabel = "Save and continue", busy, onNext, disabled }: {
  onBack?: () => void;
  nextLabel?: string;
  busy?: boolean;
  onNext?: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-6 flex justify-between gap-2 border-t border-stone-200 pt-4">
      {onBack ? (
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
      ) : (
        <span />
      )}
      <Button type={onNext ? "button" : "submit"} onClick={onNext} disabled={busy || disabled}>
        {busy ? "Saving…" : nextLabel}
      </Button>
    </div>
  );
}

// --- Step 1: school profile --------------------------------------------------

function SchoolStep({ onNext }: StepProps) {
  const { school, reloadSchool } = useAuth();
  const [form, setForm] = useState({
    name: school?.name ?? "",
    deped_school_id: school?.deped_school_id ?? "",
    address: school?.address ?? "",
    division: school?.division ?? "",
    region: school?.region ?? "",
    logo_url: school?.logo_url ?? "",
    daily: String(school?.settings.default_max_daily_hours ?? 6),
    weekly: String(school?.settings.default_max_weekly_hours ?? 30),
    saturday: school?.settings.school_days.includes(6) ?? false,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api<School>("/api/school", {
        method: "PUT",
        body: {
          name: form.name,
          deped_school_id: form.deped_school_id || null,
          address: form.address || null,
          division: form.division || null,
          region: form.region || null,
          logo_url: form.logo_url || null,
          settings: {
            default_max_daily_hours: Number(form.daily),
            default_max_weekly_hours: Number(form.weekly),
            school_days: form.saturday ? [1, 2, 3, 4, 5, 6] : [1, 2, 3, 4, 5],
          },
        },
      });
      await reloadSchool();
      onNext();
    } catch (err) {
      setError(message(err, "Could not save the school details."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="School name" required value={form.name} onChange={set("name")} wrapperClassName="sm:col-span-2" />
        <TextField label="DepEd School ID" value={form.deped_school_id} onChange={set("deped_school_id")} />
        <TextField label="Logo image URL" type="url" hint="Optional. Shown on printed schedules." value={form.logo_url} onChange={set("logo_url")} />
        <TextField label="Address" value={form.address} onChange={set("address")} wrapperClassName="sm:col-span-2" />
        <TextField label="Schools Division" value={form.division} onChange={set("division")} />
        <TextField label="Region" value={form.region} onChange={set("region")} />
      </div>

      <h3 className="mb-1 mt-6 text-sm font-semibold text-stone-900">Default teacher load limits</h3>
      <p className="mb-3 text-sm text-stone-600">
        Used for every teacher unless you set a different limit for that teacher. Confirm these against current DepEd
        rules before relying on them.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Max teaching hours per day" type="number" min={1} max={24} step="0.5" required value={form.daily} onChange={set("daily")} />
        <TextField label="Max teaching hours per week" type="number" min={1} max={100} step="0.5" required value={form.weekly} onChange={set("weekly")} />
        <label className="flex items-center gap-2 text-sm text-stone-800 sm:col-span-2">
          <input
            type="checkbox"
            className="size-4 accent-emerald-800"
            checked={form.saturday}
            onChange={(event) => setForm((current) => ({ ...current, saturday: event.target.checked }))}
          />
          Classes are also held on Saturdays
        </label>
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <StepActions busy={busy} />
    </form>
  );
}

// --- Step 2: school year and semesters -----------------------------------------

function YearStep({ onNext, onBack }: StepProps) {
  const [years, setYears] = useState<SchoolYear[] | null>(null);
  const startYear = new Date().getMonth() >= 3 ? new Date().getFullYear() : new Date().getFullYear() - 1;
  const [form, setForm] = useState({
    name: `${startYear}-${startYear + 1}`,
    start_date: "",
    end_date: "",
    s1_start: "",
    s1_end: "",
    s2_start: "",
    s2_end: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  useEffect(() => {
    api<SchoolYear[]>("/api/school-years")
      .then(setYears)
      .catch((err) => setError(message(err, "Could not load school years.")));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/school-years", {
        method: "POST",
        body: {
          name: form.name,
          start_date: form.start_date,
          end_date: form.end_date,
          first_semester: { start_date: form.s1_start || form.start_date, end_date: form.s1_end },
          second_semester: { start_date: form.s2_start, end_date: form.s2_end || form.end_date },
        },
      });
      onNext();
    } catch (err) {
      setError(message(err, "Could not save the school year."));
    } finally {
      setBusy(false);
    }
  }

  if (years === null) return error ? <Alert>{error}</Alert> : <Spinner />;

  if (years.length > 0) {
    return (
      <div>
        <p className="mb-3 text-sm text-stone-600">Your school year is already set up.</p>
        <ul className="space-y-3">
          {years.map((year) => (
            <li key={year.id} className="rounded-md border border-stone-200 p-3 text-sm">
              <p className="font-medium text-stone-900">
                School year {year.name} {year.is_active && <Badge tone="emerald">active</Badge>}
              </p>
              <p className="text-stone-600">
                {year.start_date} to {year.end_date}
              </p>
              {year.semesters.map((semester) => (
                <p key={semester.id} className="text-stone-600">
                  Semester {semester.number}: {semester.start_date} to {semester.end_date}
                </p>
              ))}
            </li>
          ))}
        </ul>
        <StepActions onBack={onBack} onNext={onNext} nextLabel="Continue" />
      </div>
    );
  }

  return (
    <form onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-3">
        <TextField label="School year" required placeholder="2026-2027" value={form.name} onChange={set("name")} />
        <TextField label="First day of classes" type="date" required value={form.start_date} onChange={set("start_date")} />
        <TextField label="Last day of classes" type="date" required value={form.end_date} onChange={set("end_date")} />
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <fieldset className="rounded-md border border-stone-200 p-4">
          <legend className="px-1 text-sm font-semibold text-stone-900">First semester</legend>
          <div className="grid gap-3">
            <TextField label="Starts" type="date" hint="Blank = first day of classes." value={form.s1_start} onChange={set("s1_start")} />
            <TextField label="Ends" type="date" required value={form.s1_end} onChange={set("s1_end")} />
          </div>
        </fieldset>
        <fieldset className="rounded-md border border-stone-200 p-4">
          <legend className="px-1 text-sm font-semibold text-stone-900">Second semester</legend>
          <div className="grid gap-3">
            <TextField label="Starts" type="date" required value={form.s2_start} onChange={set("s2_start")} />
            <TextField label="Ends" type="date" hint="Blank = last day of classes." value={form.s2_end} onChange={set("s2_end")} />
          </div>
        </fieldset>
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <StepActions onBack={onBack} busy={busy} />
    </form>
  );
}

// --- Step 3: shifts ------------------------------------------------------------

type ShiftDraft = { id?: number; name: string; start_time: string; end_time: string };

const SHIFT_PRESETS: Record<string, ShiftDraft[]> = {
  "Single shift": [{ name: "Whole day", start_time: "07:00", end_time: "17:00" }],
  "Double shift": [
    { name: "Morning", start_time: "06:00", end_time: "12:00" },
    { name: "Afternoon", start_time: "12:30", end_time: "18:30" },
  ],
};

function ShiftsStep({ onNext, onBack }: StepProps) {
  const [drafts, setDrafts] = useState<ShiftDraft[] | null>(null);
  const [removed, setRemoved] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Shift[]>("/api/shifts")
      .then((shifts) =>
        setDrafts(
          shifts.map((shift) => ({
            id: shift.id,
            name: shift.name,
            start_time: shortTime(shift.start_time),
            end_time: shortTime(shift.end_time),
          })),
        ),
      )
      .catch((err) => setError(message(err, "Could not load shifts.")));
  }, []);

  if (drafts === null) return error ? <Alert>{error}</Alert> : <Spinner />;

  const update = (index: number, patch: Partial<ShiftDraft>) =>
    setDrafts(drafts.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)));

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!drafts || drafts.length === 0) {
      setError("Add at least one shift.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      for (const id of removed) await api(`/api/shifts/${id}`, { method: "DELETE" });
      for (const draft of drafts) {
        const body = { name: draft.name, start_time: draft.start_time, end_time: draft.end_time };
        if (draft.id) await api(`/api/shifts/${draft.id}`, { method: "PUT", body });
        else await api("/api/shifts", { method: "POST", body });
      }
      onNext();
    } catch (err) {
      setError(message(err, "Could not save the shifts."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save}>
      <p className="mb-4 text-sm text-stone-600">
        A shift is a block of the day in which a set of sections has classes. Schools that share rooms between morning
        and afternoon sections use two shifts.
      </p>
      {drafts.length === 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {Object.entries(SHIFT_PRESETS).map(([label, preset]) => (
            <Button key={label} variant="secondary" onClick={() => setDrafts(preset.map((p) => ({ ...p })))}>
              Start with: {label.toLowerCase()}
            </Button>
          ))}
        </div>
      )}
      <ul className="space-y-3">
        {drafts.map((draft, index) => (
          <li key={draft.id ?? `new-${index}`} className="grid items-end gap-3 rounded-md border border-stone-200 p-3 sm:grid-cols-[1fr_9rem_9rem_auto]">
            <TextField label="Shift name" required value={draft.name} onChange={(v) => update(index, { name: v })} />
            <TextField label="Starts" type="time" required value={draft.start_time} onChange={(v) => update(index, { start_time: v })} />
            <TextField label="Ends" type="time" required value={draft.end_time} onChange={(v) => update(index, { end_time: v })} />
            <Button
              variant="danger"
              onClick={() => {
                if (draft.id) setRemoved([...removed, draft.id]);
                setDrafts(drafts.filter((_, i) => i !== index));
              }}
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
      <Button
        variant="secondary"
        className="mt-3"
        onClick={() => setDrafts([...drafts, { name: "", start_time: "07:00", end_time: "12:00" }])}
      >
        Add shift
      </Button>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <StepActions onBack={onBack} busy={busy} />
    </form>
  );
}

// --- Step 4: bell schedule -----------------------------------------------------

function BellEditor({ shift, onSaved }: { shift: Shift; onSaved: (shift: Shift) => void }) {
  const [rows, setRows] = useState<PeriodRow[]>(
    shift.periods.map((p) => ({
      name: p.name,
      start_time: shortTime(p.start_time),
      end_time: shortTime(p.end_time),
      is_break: p.is_break,
    })),
  );
  const [generator, setGenerator] = useState({ periodMinutes: "60", periodCount: "5", breakAfter: "2", breakMinutes: "20" });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(shift.periods.length > 0);
  const [busy, setBusy] = useState(false);

  const start = shortTime(shift.start_time);
  const end = shortTime(shift.end_time);

  const change = (next: PeriodRow[]) => {
    setRows(next);
    setSaved(false);
  };
  const update = (index: number, patch: Partial<PeriodRow>) =>
    change(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  const setGen = (key: keyof typeof generator) => (value: string) =>
    setGenerator((current) => ({ ...current, [key]: value }));

  function generate() {
    change(
      generateBellSchedule({
        start,
        periodMinutes: Number(generator.periodMinutes) || 60,
        periodCount: Number(generator.periodCount) || 1,
        breakAfter: Number(generator.breakAfter) || 0,
        breakMinutes: Number(generator.breakMinutes) || 0,
        breakName: "Break",
      }),
    );
    setError("");
  }

  async function save() {
    const problem = validateBellSchedule(rows, start, end);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      onSaved(await api<Shift>(`/api/shifts/${shift.id}/periods`, { method: "PUT", body: rows }));
      setSaved(true);
    } catch (err) {
      setError(message(err, "Could not save the bell schedule."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-stone-200 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-stone-900">
          {shift.name}{" "}
          <span className="font-normal text-stone-500">
            {start}–{end}
          </span>
        </h3>
        {saved ? <Badge tone="emerald">saved</Badge> : <Badge tone="amber">not saved</Badge>}
      </div>

      <div className="mb-4 grid items-end gap-3 rounded-md bg-stone-100 p-3 sm:grid-cols-5">
        <TextField label="Minutes per period" type="number" min={10} value={generator.periodMinutes} onChange={setGen("periodMinutes")} />
        <TextField label="Number of periods" type="number" min={1} max={15} value={generator.periodCount} onChange={setGen("periodCount")} />
        <TextField label="Break after period" type="number" min={0} hint="0 = no break" value={generator.breakAfter} onChange={setGen("breakAfter")} />
        <TextField label="Break minutes" type="number" min={0} value={generator.breakMinutes} onChange={setGen("breakMinutes")} />
        <Button variant="secondary" onClick={generate} className="sm:mb-5">
          Generate
        </Button>
      </div>

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-stone-600">
              <tr>
                <th scope="col" className="pb-1 pr-2 font-semibold">Name</th>
                <th scope="col" className="pb-1 pr-2 font-semibold">Starts</th>
                <th scope="col" className="pb-1 pr-2 font-semibold">Ends</th>
                <th scope="col" className="pb-1 pr-2 font-semibold">Break</th>
                <th scope="col" className="pb-1"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  <td className="py-1 pr-2">
                    <input aria-label={`Row ${index + 1} name`} className={inputClass} value={row.name} onChange={(e) => update(index, { name: e.target.value })} />
                  </td>
                  <td className="py-1 pr-2">
                    <input aria-label={`Row ${index + 1} start`} type="time" className={inputClass} value={row.start_time} onChange={(e) => update(index, { start_time: e.target.value })} />
                  </td>
                  <td className="py-1 pr-2">
                    <input aria-label={`Row ${index + 1} end`} type="time" className={inputClass} value={row.end_time} onChange={(e) => update(index, { end_time: e.target.value })} />
                  </td>
                  <td className="py-1 pr-2 text-center">
                    <input aria-label={`Row ${index + 1} is a break`} type="checkbox" className="size-4 accent-emerald-800" checked={row.is_break} onChange={(e) => update(index, { is_break: e.target.checked })} />
                  </td>
                  <td className="py-1 text-right">
                    <Button variant="ghost" small className="!text-red-700" onClick={() => change(rows.filter((_, i) => i !== index))}>
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => {
            const last = rows[rows.length - 1]?.end_time ?? start;
            change([...rows, { name: `Period ${rows.filter((r) => !r.is_break).length + 1}`, start_time: last, end_time: last, is_break: false }]);
          }}
        >
          Add row
        </Button>
        <Button onClick={save} disabled={busy || rows.length === 0}>
          {busy ? "Saving…" : `Save ${shift.name} schedule`}
        </Button>
      </div>
    </section>
  );
}

function BellStep({ onNext, onBack }: StepProps) {
  const [shifts, setShifts] = useState<Shift[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Shift[]>("/api/shifts")
      .then(setShifts)
      .catch((err) => setError(message(err, "Could not load shifts.")));
  }, []);

  if (shifts === null) return error ? <Alert>{error}</Alert> : <Spinner />;
  const ready = shifts.length > 0 && shifts.every((shift) => shift.periods.some((period) => !period.is_break));

  return (
    <div>
      <p className="mb-4 text-sm text-stone-600">
        Set the periods and breaks for each shift. Use Generate for a quick start, then adjust any row.
      </p>
      <div className="space-y-5">
        {shifts.map((shift) => (
          <BellEditor
            key={shift.id}
            shift={shift}
            onSaved={(fresh) => setShifts(shifts.map((s) => (s.id === fresh.id ? fresh : s)))}
          />
        ))}
      </div>
      {!ready && (
        <p className="mt-4 text-sm text-stone-600">Save a schedule with at least one class period for every shift to continue.</p>
      )}
      <StepActions onBack={onBack} onNext={onNext} nextLabel="Continue" disabled={!ready} />
    </div>
  );
}

// --- Step 5: strands from the template, then finish -----------------------------

type Template = { note: string; tracks: { code: string; name: string; strands: { code: string; name: string }[] }[] };

function StrandsStep({ onBack }: StepProps) {
  const { reloadSchool } = useAuth();
  const router = useRouter();
  const [template, setTemplate] = useState<Template | null>(null);
  const [existing, setExisting] = useState<Set<string>>(new Set());
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api<Template>("/api/templates/shs"), api<{ code: string }[]>("/api/strands")])
      .then(([loaded, strands]) => {
        setTemplate(loaded);
        setExisting(new Set(strands.map((strand) => strand.code)));
      })
      .catch((err) => setError(message(err, "Could not load the strand list.")));
  }, []);

  async function finish() {
    setBusy(true);
    setError("");
    try {
      if (chosen.size > 0) {
        await api("/api/templates/shs/apply", { method: "POST", body: { strand_codes: [...chosen] } });
      }
      await api("/api/onboarding/complete", { method: "POST" });
      await reloadSchool();
      router.replace("/dashboard");
    } catch (err) {
      setError(message(err, "Could not finish the setup."));
      setBusy(false);
    }
  }

  if (template === null) return error ? <Alert>{error}</Alert> : <Spinner />;

  return (
    <div>
      <p className="mb-2 text-sm text-stone-600">
        Tick the strands your school offers. Each one is added with a starter list of subjects and a sample curriculum
        per grade and semester, which you can edit afterwards. You can also skip this and enter everything yourself.
      </p>
      <Alert kind="info">
        The starter subjects, weekly hours and semester placement are samples. Check them against your school&apos;s
        approved program offering and current DepEd issuances.
      </Alert>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {template.tracks.map((track) => (
          <fieldset key={track.code} className="rounded-md border border-stone-200 p-4">
            <legend className="px-1 text-sm font-semibold text-stone-900">{track.name}</legend>
            <div className="space-y-2">
              {track.strands.map((strand) => {
                const added = existing.has(strand.code);
                return (
                  <label key={strand.code} className="flex items-start gap-2 text-sm text-stone-800">
                    <input
                      type="checkbox"
                      className="mt-0.5 size-4 accent-emerald-800"
                      disabled={added}
                      checked={added || chosen.has(strand.code)}
                      onChange={(event) => {
                        const next = new Set(chosen);
                        if (event.target.checked) next.add(strand.code);
                        else next.delete(strand.code);
                        setChosen(next);
                      }}
                    />
                    <span>
                      <span className="font-medium">{strand.code}</span> – {strand.name}{" "}
                      {added && <Badge tone="emerald">already added</Badge>}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <StepActions
        onBack={onBack}
        onNext={finish}
        busy={busy}
        nextLabel={chosen.size > 0 ? `Add ${chosen.size} strand${chosen.size > 1 ? "s" : ""} and finish` : "Finish setup"}
      />
    </div>
  );
}

// --- wizard shell --------------------------------------------------------------

export default function OnboardingPage() {
  const { user, school, loading, isAdmin } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (!isAdmin) router.replace("/dashboard");
  }, [loading, user, isAdmin, router]);

  const next = useCallback(() => setStep((current) => Math.min(current + 1, STEPS.length - 1)), []);
  const back = useCallback(() => setStep((current) => Math.max(current - 1, 0)), []);

  if (loading || !user || !school || !isAdmin) return <Spinner />;

  const stepProps = { onNext: next, onBack: step > 0 ? back : undefined };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-emerald-800">School setup</p>
          <h1 className="text-2xl font-semibold text-stone-900">{school.name}</h1>
        </div>
        {school.onboarding_completed && (
          <Button variant="secondary" onClick={() => router.push("/dashboard")}>
            Back to dashboard
          </Button>
        )}
      </div>

      <ol className="mb-6 grid grid-cols-5 gap-1 text-center text-xs sm:text-sm">
        {STEPS.map((label, index) => (
          <li
            key={label}
            aria-current={index === step ? "step" : undefined}
            className={`border-t-4 pt-2 ${
              index === step
                ? "border-emerald-800 font-semibold text-emerald-900"
                : index < step
                  ? "border-emerald-300 text-stone-700"
                  : "border-stone-200 text-stone-500"
            }`}
          >
            <span className="block sm:inline">{index + 1}.</span> {label}
          </li>
        ))}
      </ol>

      <div className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm sm:p-7">
        <h2 className="mb-4 text-lg font-semibold text-stone-900">
          Step {step + 1} of {STEPS.length}: {STEPS[step]}
        </h2>
        {step === 0 && <SchoolStep {...stepProps} />}
        {step === 1 && <YearStep {...stepProps} />}
        {step === 2 && <ShiftsStep {...stepProps} />}
        {step === 3 && <BellStep {...stepProps} />}
        {step === 4 && <StrandsStep {...stepProps} />}
      </div>
    </div>
  );
}
