"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";

type Log = {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  changes: Record<string, unknown> | unknown[] | null;
  created_at: string;
};

const SCHEDULE_TYPES = "schedule_entry,assignment,schedule";

function describe(log: Log): string {
  const changes = log.changes;
  if (changes && !Array.isArray(changes) && typeof changes.summary === "string") return changes.summary;
  const what = log.entity_type.replace(/_/g, " ");
  return log.entity_id === null ? what : `${what} #${log.entity_id}`;
}

export default function HistoryPage() {
  const { isAdmin } = useAuth();
  const [scheduleOnly, setScheduleOnly] = useState(true);
  const [logs, setLogs] = useState<Log[] | null>(null);
  const [users, setUsers] = useState<Map<number, string>>(new Map());
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    async function load() {
      try {
        const [rows, people] = await Promise.all([
          api<Log[]>("/api/audit-logs", { params: { limit: 300, entity_type: scheduleOnly ? SCHEDULE_TYPES : undefined } }),
          api<User[]>("/api/users"),
        ]);
        if (cancelled) return;
        setLogs(rows);
        setUsers(new Map(people.map((person) => [person.id, person.full_name])));
        setError("");
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the history.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [isAdmin, scheduleOnly]);

  if (!isAdmin) return <Alert kind="warning">Only administrators can see the change history.</Alert>;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-stone-900">Change history</h1>
        <p className="mt-1 max-w-2xl text-sm text-stone-600">
          Who changed what, and when. The latest 300 changes are shown, newest first.
        </p>
      </div>
      <label className="flex items-center gap-2 text-sm text-stone-700">
        <input type="checkbox" checked={scheduleOnly} onChange={(event) => setScheduleOnly(event.target.checked)} />
        Only timetable and teacher loading changes
      </label>
      {error && <Alert>{error}</Alert>}
      {!logs ? (
        !error && <Spinner />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="bg-stone-100 text-left text-xs uppercase tracking-wide text-stone-600">
              <tr>
                <th scope="col" className="px-3 py-2">When</th>
                <th scope="col" className="px-3 py-2">Who</th>
                <th scope="col" className="px-3 py-2">Action</th>
                <th scope="col" className="px-3 py-2">What</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {logs.map((log) => (
                <tr key={log.id}>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-stone-600">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {log.user_id === null ? "Removed user" : (users.get(log.user_id) ?? `User #${log.user_id}`)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge>{log.action}</Badge>
                  </td>
                  <td className="px-3 py-2">{describe(log)}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-8 text-center text-stone-500">
                    No changes recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
