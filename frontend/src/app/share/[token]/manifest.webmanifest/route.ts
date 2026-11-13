// Lets a phone add this timetable to its Home Screen as an app (iPhones only allow notifications then).
export async function GET(_request: Request, context: RouteContext<"/share/[token]/manifest.webmanifest">) {
  const { token } = await context.params;
  const start = `/share/${encodeURIComponent(token)}`;
  return Response.json(
    { name: "Class timetable", short_name: "Timetable", start_url: start, scope: start, display: "standalone", background_color: "#ffffff", theme_color: "#21468b" },
    { headers: { "Content-Type": "application/manifest+json" } },
  );
}
