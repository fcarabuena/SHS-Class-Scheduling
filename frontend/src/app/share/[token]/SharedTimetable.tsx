"use client";

import { useEffect, useState } from "react";

import { Alert, Button, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

type Shared = {
  school: string;
  heading: string;
  title: string;
  subtitle: string;
  days: string[];
  rows: { label: string; time: string; is_break: boolean; cells: string[][] }[];
};

export function SharedTimetable({ token }: { token: string }) {
  const [data, setData] = useState<Shared | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Shared>(`/api/public/timetable/${encodeURIComponent(token)}`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "This timetable could not be loaded."));
  }, [token]);

  if (error) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16">
        <Alert>{error}</Alert>
      </main>
    );
  }
  if (!data) return <Spinner />;

  return (
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-8">
      <div className="border-t-4 border-red-600 bg-primary-700 px-5 py-4 text-white print:border-0 print:bg-white print:px-0 print:text-stone-900">
        <p className="text-xs uppercase tracking-wider text-accent print:text-stone-600">{data.school}</p>
        <h1 className="mt-1 text-[1.75rem] leading-tight">{data.title}</h1>
        <p className="text-sm text-primary-100 print:text-stone-600">
          {data.subtitle} · {data.heading}
        </p>
      </div>
      <div className="flex justify-end print:hidden">
        <Button variant="secondary" onClick={() => window.print()}>
          Print
        </Button>
      </div>
      <div className="overflow-x-auto border border-stone-200 bg-white">
        <table className="w-full min-w-[40rem] table-fixed border-collapse text-sm">
          <caption className="sr-only">Weekly timetable of {data.title}</caption>
          <thead>
            <tr className="bg-stone-100 text-stone-700">
              <th scope="col" className="w-28 border-b border-r border-stone-200 px-2 py-2 text-left font-medium">
                Period
              </th>
              {data.days.map((day) => (
                <th key={day} scope="col" className="border-b border-r border-stone-200 px-2 py-2 font-medium last:border-r-0">
                  {day}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={`${row.label}-${row.time}`} className={row.is_break ? "bg-stone-50 text-stone-500" : ""}>
                <th scope="row" className="border-b border-r border-stone-200 px-2 py-1.5 text-left align-top font-normal">
                  <span className="block font-medium text-stone-800">{row.label}</span>
                  <span className="block text-xs tabular-nums text-stone-500">{row.time}</span>
                </th>
                {row.is_break ? (
                  <td colSpan={data.days.length} className="border-b border-stone-200 px-2 py-1 text-center text-xs italic">
                    Break
                  </td>
                ) : (
                  row.cells.map((lines, index) => (
                    <td key={index} className="h-14 border-b border-r border-stone-200 p-1 align-top text-xs last:border-r-0">
                      {lines.filter(Boolean).map((line, n) => (
                        <span key={n} className={`block ${n === 0 ? "font-semibold text-stone-900" : "text-stone-700"}`}>
                          {line}
                        </span>
                      ))}
                    </td>
                  ))
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-stone-500">Read-only view shared by the school. It always shows the latest timetable.</p>
    </main>
  );
}
