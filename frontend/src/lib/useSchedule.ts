"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { Overview, Room, Section, Subject, Teacher } from "./schedule";
import type { SchoolYear, Shift } from "./types";

export type ScheduleLookups = {
  sections: Section[];
  subjects: Subject[];
  teachers: Teacher[];
  rooms: Room[];
  shifts: Shift[];
  years: SchoolYear[];
};

/** Loads a semester's schedule overview plus the lists needed to label it. */
export function useSchedule() {
  const [data, setData] = useState<Overview | null>(null);
  const [lookups, setLookups] = useState<ScheduleLookups | null>(null);
  const [semesterId, setSemesterId] = useState<number | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const overview = await api<Overview>("/api/schedule", { params: { semester_id: semesterId } });
        const [sections, subjects, teachers, rooms, shifts, years] = await Promise.all([
          api<Section[]>("/api/sections", { params: { school_year_id: overview.school_year_id } }),
          api<Subject[]>("/api/subjects"),
          api<Teacher[]>("/api/teachers"),
          api<Room[]>("/api/rooms"),
          api<Shift[]>("/api/shifts"),
          api<SchoolYear[]>("/api/school-years"),
        ]);
        if (cancelled) return;
        setData(overview);
        setLookups({ sections, subjects, teachers, rooms, shifts, years });
        setError("");
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the schedule.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [semesterId]);

  /** Runs a change that answers with the fresh overview. Resolves to it, or null on failure. */
  const run = useCallback(async <T extends Overview>(change: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError("");
    try {
      const fresh = await change();
      setData(fresh);
      return fresh;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The change could not be saved.");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  return { data, lookups, error, setError, busy, run, semesterId: data?.semester_id ?? semesterId, setSemesterId };
}

export function semesterOptions(years: SchoolYear[]): { value: number; label: string }[] {
  return years.flatMap((year) =>
    year.semesters.map((semester) => ({
      value: semester.id,
      label: `${year.name} · ${semester.number === 1 ? "1st" : "2nd"} semester`,
    })),
  );
}
