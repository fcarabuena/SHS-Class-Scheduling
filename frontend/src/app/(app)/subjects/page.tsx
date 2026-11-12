"use client";

import { ResourcePage } from "@/components/ResourcePage";
import { Badge } from "@/components/ui";
import { labelOf, ROOM_TYPES, SUBJECT_TYPES } from "@/lib/types";

const TYPE_TONE = { core: "sky", applied: "amber", specialized: "emerald" } as const;

export default function SubjectsPage() {
  return (
    <ResourcePage
      title="Subjects"
      description="Core, applied and specialized subjects with their weekly hours and the kind of room they need."
      endpoint="/api/subjects"
      importResource="subjects"
      columns={[
        { header: "Code", cell: (row) => <span className="whitespace-nowrap font-medium">{row.code}</span> },
        { header: "Name", cell: (row) => row.name },
        {
          header: "Type",
          cell: (row) => (
            <Badge tone={TYPE_TONE[row.type as keyof typeof TYPE_TONE]}>{labelOf(SUBJECT_TYPES, row.type)}</Badge>
          ),
        },
        { header: "Hours / week", cell: (row) => <span className="tabular-nums">{row.hours_per_week}</span> },
        { header: "Room needed", cell: (row) => labelOf(ROOM_TYPES, row.required_room_type) },
        { header: "Heavy", cell: (row) => (row.is_heavy ? "Yes" : "") },
      ]}
      fields={[
        { name: "code", label: "Code", type: "text", required: true },
        { name: "type", label: "Type", type: "select", required: true, options: () => SUBJECT_TYPES },
        { name: "name", label: "Name", type: "text", required: true, full: true },
        { name: "hours_per_week", label: "Hours per week", type: "number", step: "0.5", required: true },
        {
          name: "required_room_type",
          label: "Room needed",
          type: "select",
          required: true,
          options: () => ROOM_TYPES,
        },
        {
          name: "is_heavy",
          label: "Heavy subject (keep out of the last period)",
          type: "checkbox",
          full: true,
        },
      ]}
      defaults={{ code: "", name: "", type: "core", hours_per_week: 4, required_room_type: "lecture", is_heavy: false }}
      searchText={(row) => `${row.code} ${row.name} ${row.type}`}
    />
  );
}
