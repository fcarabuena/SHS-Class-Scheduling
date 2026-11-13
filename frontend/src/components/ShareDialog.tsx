"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { ViewKind } from "@/lib/schedule";

import { Alert, Badge, Button, Field, inputClass, Modal } from "./ui";

type ShareLink = {
  id: number;
  view: ViewKind;
  target_id: number;
  url: string;
  expires_at: string | null;
  status: "active" | "expired" | "revoked";
  view_count: number;
};

type Props = { view: ViewKind; targetId: number; label: string; semesterId: number; onClose: () => void };

/** Public read-only links to the timetable on screen. */
export function ShareDialog({ view, targetId, label, semesterId, onClose }: Props) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [expiry, setExpiry] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<ShareLink[]>("/api/share-links", { params: { semester_id: semesterId } })
      .then(setLinks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the links."));
  }, [semesterId]);

  const mine = (links ?? []).filter((link) => link.view === view && link.target_id === targetId);

  async function create() {
    setError("");
    try {
      const body = { view, target_id: targetId, semester_id: semesterId, expires_in_days: expiry ? Number(expiry) : null };
      const link = await api<ShareLink>("/api/share-links", { method: "POST", body });
      setLinks((current) => [link, ...(current ?? [])]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the link.");
    }
  }

  async function revoke(id: number) {
    setError("");
    try {
      await api(`/api/share-links/${id}`, { method: "DELETE" });
      setLinks((current) => (current ?? []).filter((link) => link.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not turn the link off.");
    }
  }

  async function copy(link: ShareLink) {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(link.id);
    } catch {
      setError("Copying is blocked by the browser. Select the link and copy it by hand.");
    }
  }

  return (
    <Modal title={`Share the timetable of ${label}`} onClose={onClose} wide>
      <div className="space-y-4">
        <p className="text-sm text-stone-600">
          Anyone with the link can view this one timetable without signing in, and nothing else. It always shows the
          latest version. Turn a link off at any time.
        </p>
        {error && <Alert>{error}</Alert>}
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Link works" className="w-48">
            {(id) => (
              <select id={id} className={inputClass} value={expiry} onChange={(event) => setExpiry(event.target.value)}>
                <option value="">Until turned off</option>
                <option value="7">For 7 days</option>
                <option value="30">For 30 days</option>
                <option value="180">For one semester</option>
              </select>
            )}
          </Field>
          <Button onClick={create}>Create link</Button>
        </div>
        {links === null ? (
          <p className="text-sm text-stone-500">Loading…</p>
        ) : mine.length === 0 ? (
          <p className="text-sm text-stone-600">No links for this timetable yet.</p>
        ) : (
          <ul className="divide-y divide-stone-100 border border-stone-200">
            {mine.map((link) => (
              <li key={link.id} className="space-y-2 px-3 py-2 text-sm">
                <input
                  readOnly
                  aria-label="Share link"
                  className={`${inputClass} font-mono text-xs`}
                  value={link.url}
                  onFocus={(event) => event.target.select()}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={link.status === "active" ? "emerald" : "amber"}>
                    {link.status === "active" ? "Active" : "Expired"}
                  </Badge>
                  <span className="text-xs text-stone-600">
                    {link.expires_at ? `Until ${new Date(link.expires_at).toLocaleDateString()}` : "No end date"} · opened{" "}
                    {link.view_count} time{link.view_count === 1 ? "" : "s"}
                  </span>
                  <span className="ml-auto flex gap-2">
                    <Button variant="secondary" small onClick={() => copy(link)}>
                      {copied === link.id ? "Copied" : "Copy"}
                    </Button>
                    <Button variant="danger" small onClick={() => revoke(link.id)}>
                      Turn off
                    </Button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
