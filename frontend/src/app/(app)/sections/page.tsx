"use client";

import { ResourcePage } from "@/components/ResourcePage";

export default function SectionsPage() {
  return (
    <ResourcePage
      title="Sections"
      description="Class sections for the active school year. Only a head count is stored, never student names."
      endpoint="/api/sections"
      importResource="sections"
      lookups={{ strands: "/api/strands", shifts: "/api/shifts", teachers: "/api/teachers" }}
      columns={[
        { header: "Section", cell: (row) => <span className="font-medium">{row.name}</span> },
        { header: "Grade", cell: (row) => row.grade_level },
        { header: "Strand", cell: (row, l) => l.strands?.find((s) => s.id === row.strand_id)?.code ?? "—" },
        { header: "Shift", cell: (row, l) => l.shifts?.find((s) => s.id === row.shift_id)?.name ?? "—" },
        { header: "Adviser", cell: (row, l) => l.teachers?.find((t) => t.id === row.adviser_id)?.full_name ?? "—" },
        { header: "Students", cell: (row) => <span className="tabular-nums">{row.student_count}</span> },
      ]}
      fields={[
        { name: "name", label: "Section name", type: "text", required: true },
        {
          name: "grade_level",
          label: "Grade level",
          type: "select",
          required: true,
          options: () => [
            { value: 11, label: "Grade 11" },
            { value: 12, label: "Grade 12" },
          ],
        },
        {
          name: "strand_id",
          label: "Strand",
          type: "select",
          required: true,
          options: (l) => (l.strands ?? []).map((s) => ({ value: s.id, label: `${s.code} – ${s.name}` })),
        },
        {
          name: "shift_id",
          label: "Shift",
          type: "select",
          required: true,
          options: (l) => (l.shifts ?? []).map((s) => ({ value: s.id, label: s.name })),
        },
        {
          name: "adviser_id",
          label: "Adviser",
          type: "select",
          nullable: true,
          options: (l) => (l.teachers ?? []).map((t) => ({ value: t.id, label: t.full_name })),
        },
        { name: "student_count", label: "Number of students", type: "number", required: true },
      ]}
      defaults={{ name: "", grade_level: 11, strand_id: "", shift_id: "", adviser_id: "", student_count: 40 }}
      searchText={(row, l) => `${row.name} ${l.strands?.find((s) => s.id === row.strand_id)?.code ?? ""}`}
    />
  );
}
