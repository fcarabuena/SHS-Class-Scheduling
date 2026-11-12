"use client";

import { ResourcePage } from "@/components/ResourcePage";
import { labelOf, ROOM_TYPES } from "@/lib/types";

export default function RoomsPage() {
  return (
    <ResourcePage
      title="Rooms"
      description="Classrooms, laboratories, shops and other teaching spaces with their seating capacity."
      endpoint="/api/rooms"
      importResource="rooms"
      columns={[
        { header: "Code", cell: (row) => <span className="font-medium">{row.code}</span> },
        { header: "Name", cell: (row) => row.name },
        { header: "Type", cell: (row) => labelOf(ROOM_TYPES, row.type) },
        { header: "Capacity", cell: (row) => <span className="tabular-nums">{row.capacity}</span> },
      ]}
      fields={[
        { name: "code", label: "Code", type: "text", required: true },
        { name: "name", label: "Name", type: "text", required: true },
        { name: "type", label: "Type", type: "select", required: true, options: () => ROOM_TYPES },
        { name: "capacity", label: "Capacity (students)", type: "number", required: true },
      ]}
      defaults={{ code: "", name: "", type: "lecture", capacity: 45 }}
      searchText={(row) => `${row.code} ${row.name} ${labelOf(ROOM_TYPES, row.type)}`}
    />
  );
}
