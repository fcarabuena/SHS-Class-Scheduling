"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Overview, SolverJob } from "@/lib/schedule";
import { formatHours, percentOf } from "@/lib/schedule";

import { Alert, Button, Field, inputClass, Modal } from "./ui";

type Props = {
  semesterId: number;
  onApplied: (overview: Overview) => void;
  onClose: () => void;
};

const MODES = [
  {
    value: "rebuild",
    label: "Rebuild the timetable",
    hint: "Pinned classes stay where they are. Everything else is placed again from scratch.",
  },
  {
    value: "fill",
    label: "Fill in what is missing",
    hint: "Every class already on the timetable stays. Only the hours still to place are added.",
  },
] as const;

const isActive = (job: SolverJob | null) => job?.status === "queued" || job?.status === "running";

/** Starts the automatic scheduler, shows its progress, and applies the result on request. */
export function AutoScheduleDialog({ semesterId, onApplied, onClose }: Props) {
  const [job, setJob] = useState<SolverJob | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<"rebuild" | "fill">("rebuild");
  const [timeLimit, setTimeLimit] = useState("30");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Pick up a run that is still going (or waiting to be applied) from an earlier visit.
  useEffect(() => {
    let cancelled = false;
    api<SolverJob | null>("/api/solver/jobs/latest", { params: { semester_id: semesterId } })
      .then((latest) => {
        if (cancelled) return;
        if (latest && (isActive(latest) || (latest.status === "done" && !latest.applied_at))) setJob(latest);
        setLoaded(true);
      })
      .catch(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [semesterId]);

  const jobId = job?.id;
  const active = isActive(job);
  useEffect(() => {
    if (!active || jobId === undefined) return;
    const timer = window.setInterval(() => {
      api<SolverJob>(`/api/solver/jobs/${jobId}`)
        .then(setJob)
        .catch(() => undefined);
    }, 700);
    return () => window.clearInterval(timer);
  }, [active, jobId]);

  async function call<T>(action: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError("");
    try {
      return await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    const body = { semester_id: semesterId, mode, time_limit: Math.min(300, Math.max(5, Number(timeLimit) || 30)) };
    const started = await call(() => api<SolverJob>("/api/solver/jobs", { method: "POST", body }));
    if (started) setJob(started);
  }

  async function apply() {
    if (!job) return;
    const fresh = await call(() => api<Overview>(`/api/solver/jobs/${job.id}/apply`, { method: "POST" }));
    if (fresh) {
      onApplied(fresh);
      onClose();
    }
  }

  const progress = job?.progress;
  const result = job?.result;

  return (
    <Modal title="Auto-schedule" onClose={onClose} wide>
      <div className="space-y-4">
        {error && <Alert>{error}</Alert>}
        {!loaded && <p className="text-sm text-stone-500">Loading…</p>}

        {loaded && !job && (
          <>
            <p className="text-sm text-stone-600">
              The scheduler places classes so that no teacher, room or section is double-booked and every limit is
              respected. You see the result first; nothing changes until you apply it.
            </p>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-sm font-medium text-stone-800">What should it do?</legend>
              {MODES.map((option) => (
                <label key={option.value} className="flex items-start gap-2 rounded-md border border-stone-200 p-3 text-sm">
                  <input
                    type="radio"
                    name="solver-mode"
                    className="mt-1"
                    checked={mode === option.value}
                    onChange={() => setMode(option.value)}
                  />
                  <span>
                    <span className="block font-medium text-stone-900">{option.label}</span>
                    <span className="block text-stone-600">{option.hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            <Field label="Time limit (seconds)" hint="5 to 300. Longer runs can find a tidier timetable." className="w-56">
              {(id) => (
                <input
                  id={id}
                  type="number"
                  min={5}
                  max={300}
                  className={inputClass}
                  value={timeLimit}
                  onChange={(event) => setTimeLimit(event.target.value)}
                />
              )}
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button disabled={busy} onClick={start}>
                Start
              </Button>
            </div>
          </>
        )}

        {job && active && (
          <div className="space-y-3">
            <p className="text-sm text-stone-700" role="status">
              Working… {progress?.solutions ? `${progress.solutions} timetable${progress.solutions === 1 ? "" : "s"} found so far.` : "building the first timetable."}
            </p>
            <div
              role="progressbar"
              aria-label="Hours placed"
              aria-valuemin={0}
              aria-valuemax={progress?.required_hours ?? 0}
              aria-valuenow={progress?.placed_hours ?? 0}
              className="h-2 overflow-hidden rounded bg-stone-200"
            >
              <div
                className="h-full rounded bg-emerald-600 transition-all"
                style={{ width: `${percentOf(progress?.placed_hours ?? 0, progress?.required_hours ?? 0)}%` }}
              />
            </div>
            <p className="text-sm tabular-nums text-stone-600">
              {formatHours(progress?.placed_hours ?? 0)} of {formatHours(progress?.required_hours ?? 0)} placed ·{" "}
              {Math.round(progress?.seconds ?? 0)} s of up to {job.time_limit} s
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                Keep running in the background
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={() => call(() => api<SolverJob>(`/api/solver/jobs/${job.id}/cancel`, { method: "POST" }))}
              >
                Stop and use the best so far
              </Button>
            </div>
          </div>
        )}

        {job && job.status === "failed" && (
          <>
            <Alert>{job.error ?? "The scheduler stopped unexpectedly."}</Alert>
            <div className="flex justify-end">
              <Button onClick={() => setJob(null)}>Try again</Button>
            </div>
          </>
        )}

        {job && job.status === "done" && result && (
          <div className="space-y-4">
            {result.status === "nothing_to_do" ? (
              <Alert kind="info">There is nothing to schedule yet. Add subjects on the Teacher loading page first.</Alert>
            ) : (
              <Alert kind={result.status === "complete" ? "success" : "warning"}>
                {result.status === "complete"
                  ? `Every class fits: ${formatHours(result.placed_hours)} placed with no conflicts.`
                  : `${formatHours(result.placed_hours)} of ${formatHours(result.required_hours)} can be placed without conflicts. ${formatHours(result.required_hours - result.placed_hours)} does not fit; the reasons are below.`}
              </Alert>
            )}
            <p className="text-sm text-stone-700">
              Applying this adds {result.added} class{result.added === 1 ? "" : "es"}, keeps {result.kept} and removes{" "}
              {result.removed} from the current timetable. Found in{" "}
              {result.seconds < 1 ? "under a second" : `${Math.round(result.seconds)} s`}
              {result.stopped_early ? " (stopped early)" : ""}.
            </p>

            {result.problems.length > 0 && (
              <section aria-label="Things to fix in your data">
                <h3 className="text-sm font-semibold text-stone-900">Things to fix in your data</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-800">
                  {result.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </section>
            )}
            {result.shortages.length > 0 && (
              <section aria-label="What could not be placed">
                <h3 className="text-sm font-semibold text-stone-900">
                  What could not be placed ({result.shortages.length})
                </h3>
                <ul className="mt-1 max-h-56 list-disc space-y-1 overflow-y-auto pl-5 text-sm text-stone-800">
                  {result.shortages.map((shortage) => (
                    <li key={shortage.message}>{shortage.message}</li>
                  ))}
                </ul>
              </section>
            )}

            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="secondary" onClick={() => setJob(null)}>
                Discard and run again
              </Button>
              {result.status !== "nothing_to_do" && (
                <Button disabled={busy} onClick={apply}>
                  Apply this timetable
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
