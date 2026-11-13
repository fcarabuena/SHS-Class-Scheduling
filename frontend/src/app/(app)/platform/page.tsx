"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Spinner, inputClass } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type SchoolRow = {
  id: number;
  name: string;
  division: string | null;
  status: "active" | "suspended";
  plan: string;
  plan_renews_at: string | null;
  created_at: string;
  last_activity: string | null;
  users: number;
  teachers: number;
  sections: number;
  classes: number;
};
type Listing = { plans: { code: string; name: string }[]; schools: SchoolRow[] };

/** Everything the service operator needs about every school, and nothing about their people or timetables. */
export default function PlatformPage() {
  const { user } = useAuth();
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.is_platform_admin) return;
    api<Listing>("/api/platform/schools")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the schools."));
  }, [user]);

  if (!user?.is_platform_admin) return <Alert kind="warning">Only the service administrator can see this page.</Alert>;
  if (!data) return error ? <Alert>{error}</Alert> : <Spinner />;

  async function change(school: SchoolRow, body: Partial<Pick<SchoolRow, "status" | "plan">>) {
    if (body.status === "suspended" && !window.confirm(`Suspend ${school.name}? Its users are signed out and its share links stop working.`)) return;
    setError("");
    try {
      const updated = await api<Pick<SchoolRow, "id" | "status" | "plan">>(`/api/platform/schools/${school.id}`, { method: "PUT", body });
      setData((current) => current && { ...current, schools: current.schools.map((s) => (s.id === updated.id ? { ...s, ...updated } : s)) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The change was not saved.");
    }
  }

  const active = data.schools.filter((s) => s.status === "active").length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[1.75rem] font-normal leading-tight text-stone-900">All schools</h1>
        <p className="mt-1 text-sm text-stone-600">
          {data.schools.length} school{data.schools.length === 1 ? "" : "s"} registered, {active} active. Only counts are
          shown here; each school&apos;s own data stays private to it.
        </p>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="overflow-x-auto border border-stone-200 bg-white">
        <table className="w-full min-w-[56rem] text-sm">
          <thead className="bg-stone-100 text-left text-xs uppercase tracking-wide text-stone-600">
            <tr>
              <th scope="col" className="px-3 py-2">School</th>
              <th scope="col" className="px-3 py-2 text-right">Users</th>
              <th scope="col" className="px-3 py-2 text-right">Teachers</th>
              <th scope="col" className="px-3 py-2 text-right">Sections</th>
              <th scope="col" className="px-3 py-2 text-right">Classes</th>
              <th scope="col" className="px-3 py-2">Last activity</th>
              <th scope="col" className="px-3 py-2">Plan</th>
              <th scope="col" className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {data.schools.map((school) => (
              <tr key={school.id}>
                <td className="px-3 py-2">
                  <span className="font-medium text-stone-900">{school.name}</span>
                  <span className="block text-xs text-stone-500">
                    {school.division ? `${school.division} · ` : ""}since {new Date(school.created_at).toLocaleDateString()}
                  </span>
                </td>
                {[school.users, school.teachers, school.sections, school.classes].map((value, index) => (
                  <td key={index} className="px-3 py-2 text-right tabular-nums">
                    {value}
                  </td>
                ))}
                <td className="px-3 py-2 text-xs text-stone-600">
                  {school.last_activity ? new Date(school.last_activity).toLocaleDateString() : "—"}
                </td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Plan of ${school.name}`}
                    className={`${inputClass} min-w-32`}
                    value={school.plan}
                    onChange={(event) => change(school, { plan: event.target.value })}
                  >
                    {data.plans.map((plan) => (
                      <option key={plan.code} value={plan.code}>
                        {plan.name}
                      </option>
                    ))}
                  </select>
                  {school.plan_renews_at && <span className="block text-xs text-stone-500">renews {school.plan_renews_at}</span>}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Badge tone={school.status === "active" ? "emerald" : "amber"}>
                      {school.status === "active" ? "Active" : "Suspended"}
                    </Badge>
                    {school.id !== user.school_id && (
                      <button
                        type="button"
                        className="text-xs text-primary-700 underline"
                        onClick={() => change(school, { status: school.status === "active" ? "suspended" : "active" })}
                      >
                        {school.status === "active" ? `Suspend ${school.name}` : `Reactivate ${school.name}`}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
