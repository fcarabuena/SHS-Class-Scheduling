"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { Alert, Button, inputClass, Modal } from "./ui";

type Signatory = { label: string; name: string; position: string };

const STARTER: Signatory[] = [
  { label: "Prepared by", name: "", position: "" },
  { label: "Approved", name: "", position: "" },
];

/** The people whose names are printed under exported timetables for signing. */
export function SignatoriesDialog({ onClose }: { onClose: () => void }) {
  const { school, reloadSchool } = useAuth();
  const saved = (school?.settings.signatories as Signatory[] | undefined) ?? [];
  const [rows, setRows] = useState<Signatory[]>(saved.length ? saved : STARTER);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const change = (index: number, key: keyof Signatory, value: string) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  async function save() {
    if (!school) return;
    const filled = rows.filter((row) => row.name.trim() || row.position.trim());
    if (filled.some((row) => !row.label.trim() || !row.name.trim())) {
      setError("Each person needs a line such as “Prepared by” and a name. Remove the rows you do not need.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/api/school", { method: "PUT", body: { name: school.name, settings: { signatories: filled } } });
      await reloadSchool();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the signatories.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Signatories on printed timetables" onClose={onClose} wide>
      <div className="space-y-4">
        <p className="text-sm text-stone-600">
          These names are printed under every exported timetable (Excel and PDF) with space to sign. Up to six people.
        </p>
        {error && <Alert>{error}</Alert>}
        <div className="space-y-2">
          {rows.map((row, index) => (
            <fieldset key={index} className="grid gap-2 sm:grid-cols-[1fr_1.3fr_1.3fr_auto]">
              <legend className="sr-only">Signatory {index + 1}</legend>
              <input
                aria-label={`Signatory ${index + 1} line`}
                className={inputClass}
                placeholder="Prepared by"
                maxLength={60}
                value={row.label}
                onChange={(event) => change(index, "label", event.target.value)}
              />
              <input
                aria-label={`Signatory ${index + 1} name`}
                className={inputClass}
                placeholder="Full name"
                maxLength={120}
                value={row.name}
                onChange={(event) => change(index, "name", event.target.value)}
              />
              <input
                aria-label={`Signatory ${index + 1} position`}
                className={inputClass}
                placeholder="Position"
                maxLength={120}
                value={row.position}
                onChange={(event) => change(index, "position", event.target.value)}
              />
              <Button
                variant="ghost"
                small
                aria-label={`Remove signatory ${index + 1}`}
                onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
              >
                Remove
              </Button>
            </fieldset>
          ))}
        </div>
        <div className="flex flex-wrap justify-between gap-2">
          <Button
            variant="secondary"
            disabled={rows.length >= 6}
            onClick={() => setRows((current) => [...current, { label: "", name: "", position: "" }])}
          >
            Add a person
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={busy} onClick={save}>
              Save signatories
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
