"use client";

import { useState } from "react";

import { ResourcePage } from "@/components/ResourcePage";

export default function StrandsPage() {
  // Bumped when tracks change so the strand form reloads its track list.
  const [tracksVersion, setTracksVersion] = useState(0);

  return (
    <div className="space-y-12">
      <ResourcePage
        key={tracksVersion}
        title="Strands"
        description="The strands your school offers. Each strand belongs to a track and has its own curriculum."
        endpoint="/api/strands"
        importResource="strands"
        lookups={{ tracks: "/api/tracks" }}
        columns={[
          { header: "Code", cell: (row) => <span className="font-medium">{row.code}</span> },
          { header: "Name", cell: (row) => row.name },
          { header: "Track", cell: (row, l) => l.tracks?.find((t) => t.id === row.track_id)?.name ?? "—" },
        ]}
        fields={[
          {
            name: "track_id",
            label: "Track",
            type: "select",
            required: true,
            options: (l) => (l.tracks ?? []).map((t) => ({ value: t.id, label: `${t.code} – ${t.name}` })),
          },
          { name: "code", label: "Code", type: "text", required: true, hint: "Short code, e.g. STEM" },
          { name: "name", label: "Name", type: "text", required: true, full: true },
        ]}
        defaults={{ track_id: "", code: "", name: "" }}
        searchText={(row) => `${row.code} ${row.name}`}
      />

      <ResourcePage
        title="Tracks"
        description="Tracks group strands (for example Academic or TVL). Add a track before adding its strands."
        endpoint="/api/tracks"
        columns={[
          { header: "Code", cell: (row) => <span className="font-medium">{row.code}</span> },
          { header: "Name", cell: (row) => row.name },
        ]}
        fields={[
          { name: "code", label: "Code", type: "text", required: true },
          { name: "name", label: "Name", type: "text", required: true },
        ]}
        defaults={{ code: "", name: "" }}
        searchText={(row) => `${row.code} ${row.name}`}
        onChanged={() => setTracksVersion((version) => version + 1)}
      />
    </div>
  );
}
