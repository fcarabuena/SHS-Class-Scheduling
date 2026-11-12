import { expect, type APIRequestContext } from "@playwright/test";

export const API = "http://localhost:8001";
export const PASSWORD = "Str0ng-Passw0rd!";

/** Builds a small school through the API so the test can go straight to scheduling. */
export async function setUpSchool(request: APIRequestContext, email: string, school: string) {
  const registered = await request.post(`${API}/api/auth/register`, {
    data: { school_name: school, full_name: "Test Admin", email, password: PASSWORD },
  });
  expect(registered.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registered.json()).access_token}` };
  const send = async (method: "post" | "put", path: string, data: unknown) => {
    const response = await request[method](`${API}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBe(true);
    return response.json();
  };

  await send("post", "/api/school-years", {
    name: "2026-2027",
    start_date: "2026-06-15",
    end_date: "2027-03-31",
    first_semester: { start_date: "2026-06-15", end_date: "2026-10-30" },
    second_semester: { start_date: "2026-11-09", end_date: "2027-03-31" },
  });
  const shift = await send("post", "/api/shifts", { name: "Morning", start_time: "07:00", end_time: "12:00" });
  const bell = await send("put", `/api/shifts/${shift.id}/periods`, [
    { name: "Period 1", start_time: "07:00", end_time: "08:00" },
    { name: "Period 2", start_time: "08:00", end_time: "09:00" },
    { name: "Recess", start_time: "09:00", end_time: "09:20", is_break: true },
    { name: "Period 3", start_time: "09:20", end_time: "10:20" },
  ]);
  await send("post", "/api/onboarding/complete", {});

  const track = await send("post", "/api/tracks", { code: "ACAD", name: "Academic Track" });
  const strand = await send("post", "/api/strands", { track_id: track.id, code: "STEM", name: "STEM" });
  const math = await send("post", "/api/subjects", { code: "MATH", name: "Mathematics", type: "core", hours_per_week: 2 });
  const sci = await send("post", "/api/subjects", { code: "SCI", name: "Science", type: "core", hours_per_week: 2 });
  await send("post", "/api/teachers", { employee_id: "T-1", full_name: "Ana Cruz", qualified_subject_ids: [math.id, sci.id] });
  await send("post", "/api/teachers", { employee_id: "T-2", full_name: "Ben Reyes", qualified_subject_ids: [math.id] });
  await send("post", "/api/rooms", { code: "R1", name: "Room 1", capacity: 45 });
  await send("post", "/api/rooms", { code: "R2", name: "Room 2", capacity: 45 });
  for (const name of ["11-A", "11-B"]) {
    await send("post", "/api/sections", { name, strand_id: strand.id, grade_level: 11, shift_id: shift.id, student_count: 40 });
  }
  for (const subject of [math, sci]) {
    await send("post", "/api/curriculum", { strand_id: strand.id, subject_id: subject.id, grade_level: 11, semester_number: 1 });
  }
  const teaching = bell.periods.filter((p: { is_break: boolean }) => !p.is_break);
  return { p1: teaching[0].id as number, p2: teaching[1].id as number, send, headers };
}
