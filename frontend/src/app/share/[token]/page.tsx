import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { SharedTimetable } from "./SharedTimetable";

/** Public, read-only timetable opened from a share link. No sign-in. */
export default function SharePage({ params }: PageProps<"/share/[token]">) {
  return (
    <Suspense fallback={<Spinner />}>
      {params.then(({ token }) => (
        <SharedTimetable token={token} />
      ))}
    </Suspense>
  );
}
