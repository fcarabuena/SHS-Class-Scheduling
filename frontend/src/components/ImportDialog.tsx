"use client";

import { useState } from "react";

import { api, ApiError, download } from "@/lib/api";

import { Alert, Button, Modal } from "./ui";

type ImportResult = {
  dry_run: boolean;
  created: number;
  updated: number;
  errors: { row: number; message: string }[];
};

type Props = { resource: string; title: string; onClose: () => void; onImported: () => void };

export function ImportDialog({ resource, title, onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await api<ImportResult>(`/api/import/${resource}`, {
        method: "POST",
        form,
        params: { dry_run: dryRun },
      });
      setResult(response);
      if (!dryRun && response.created + response.updated > 0) onImported();
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.message : "The import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Import ${title.toLowerCase()}`} onClose={onClose}>
      <div className="space-y-4 text-sm text-stone-700">
        <p>
          Upload a <strong>.csv</strong> or <strong>.xlsx</strong> file. Rows that match an existing record are
          updated; new ones are added. Rows with problems are skipped and listed below.
        </p>
        <Button
          variant="secondary"
          small
          onClick={() => download(`/api/import/${resource}/template`, `${resource}-template.csv`).catch(() => setError("Could not download the template."))}
        >
          Download template
        </Button>

        <input
          type="file"
          accept=".csv,.xlsx"
          aria-label="File to import"
          className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-stone-200 file:px-3 file:py-2 file:text-sm file:font-medium"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setResult(null);
            setError("");
          }}
        />

        {error && <Alert>{error}</Alert>}

        {result && (
          <div className="space-y-2">
            <Alert kind={result.errors.length ? "warning" : "success"}>
              {result.dry_run ? "Check only (nothing saved): " : "Import finished: "}
              {result.created} to add, {result.updated} to update, {result.errors.length} with problems.
            </Alert>
            {result.errors.length > 0 && (
              <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-stone-200 p-3">
                {result.errors.map((item) => (
                  <li key={item.row}>
                    <span className="font-medium">Row {item.row}:</span> {item.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button variant="secondary" disabled={!file || busy} onClick={() => run(true)}>
            Check file
          </Button>
          <Button disabled={!file || busy} onClick={() => run(false)}>
            {busy ? "Working…" : "Import"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
