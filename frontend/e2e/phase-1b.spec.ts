import { expect, test, type APIRequestContext } from "@playwright/test";

const SHOTS = "D:/Temp/shots";
const API = "http://localhost:8001";
const PASSWORD = "Str0ng-Passw0rd!";
const EMAIL = "admin@timetable.example";

/** Builds a small school through the API so the test can go straight to scheduling. */
async function setUpSchool(request: APIRequestContext) {
  const registered = await request.post(`${API}/api/auth/register`, {
    data: { school_name: "Timetable Test School", full_name: "Timetable Admin", email: EMAIL, password: PASSWORD },
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
  return { p1: teaching[0].id as number, p2: teaching[1].id as number };
}

test("load teachers, build a timetable by drag and drop, fix a conflict, switch views, export, see history", async ({
  page,
  request,
}) => {
  const { p1, p2 } = await setUpSchool(request);

  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // --- teacher loading ---------------------------------------------------------
  await page.getByRole("link", { name: "Teacher loading" }).click();
  await page.getByRole("button", { name: "Add subjects from curriculum" }).click();
  await expect(page.getByText("Added 4 subjects from the curriculum.")).toBeVisible();
  await expect(page.getByText("4 of 4 without a teacher")).toBeVisible();

  await page.getByLabel("Teacher for 11-A MATH").selectOption({ label: "Ana Cruz (0 h of 30 h)" });
  await expect(page.getByText("3 of 4 without a teacher")).toBeVisible();
  await page.getByLabel("Teacher for 11-B SCI").selectOption({ label: "Ana Cruz (2 h of 30 h)" });
  const loads = page.getByRole("region", { name: "Teacher loads" });
  await expect(loads.getByRole("listitem").filter({ hasText: "Ana Cruz" })).toContainText("4 h of 30 h");

  // An unqualified choice is allowed but flagged.
  await page.getByLabel("Teacher for 11-A SCI").selectOption({ label: "Ben Reyes (0 h of 30 h)" });
  await expect(loads.getByText("Not qualified for: SCI.")).toBeVisible();
  await expect(page.getByText("1 teacher needs attention")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/8-teacher-loading.png`, fullPage: true });
  await page.getByLabel("Teacher for 11-A SCI").selectOption({ label: "No teacher yet" });
  await expect(page.getByText("0 teachers need attention")).toBeVisible();

  // --- timetable: drag and drop ------------------------------------------------
  await page.getByRole("link", { name: "Timetable" }).click();
  await expect(page.getByRole("combobox", { name: "Section", exact: true })).toHaveValue(/\d+/);
  const palette = page.getByRole("region", { name: "Classes to place" });
  const cell = (day: number, period: number) => page.locator(`[data-cell="${day}:${period}"]`);

  await palette.getByRole("button", { name: /^MATH/ }).dragTo(cell(1, p1));
  await expect(cell(1, p1).getByRole("button", { name: "MATH, Mon Period 1" })).toBeVisible();
  await expect(cell(1, p1)).toContainText("Ana Cruz");
  await expect(cell(1, p1)).toContainText("Room 1");
  await expect(palette.getByRole("button", { name: /^MATH/ })).toContainText("1 h left");

  // Drag the placed class to Tuesday.
  await cell(1, p1).getByRole("button", { name: /^MATH/ }).dragTo(cell(2, p2));
  await expect(cell(2, p2).getByRole("button", { name: "MATH, Tue Period 2" })).toBeVisible();
  await expect(cell(1, p1).getByRole("button", { name: /^MATH/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Close selected class" }).click();
  await cell(2, p2).getByRole("button", { name: /^MATH/ }).dragTo(cell(1, p1));
  await expect(cell(1, p1).getByRole("button", { name: /^MATH/ })).toBeVisible();

  // --- real-time conflict detection and a suggested fix -------------------------
  await page.getByRole("combobox", { name: "Section", exact: true }).selectOption({ label: "11-B" });
  await palette.getByRole("button", { name: /^SCI/ }).click(); // pick up, then click a slot
  await expect(cell(1, p1)).toHaveAttribute("data-status", "conflict"); // Ana already teaches 11-A then
  await expect(cell(1, p2)).toHaveAttribute("data-status", "ok");
  await page.screenshot({ path: `${SHOTS}/9-timetable-drop-targets.png`, fullPage: true });
  await page.getByRole("button", { name: "Mon Period 1: place here despite a conflict" }).click();
  await expect(page.getByText("1 conflict", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Conflicts" })).toContainText(
    "Teacher Ana Cruz has two classes at the same time on Monday Period 1",
  );

  await cell(1, p1).getByRole("button", { name: /^SCI/ }).click();
  const selected = page.getByRole("region", { name: "Selected class" });
  await expect(selected.getByRole("heading", { name: "Suggested fixes" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/10-timetable-conflict-fixes.png`, fullPage: true });
  await selected.getByRole("button", { name: /Move to Monday Period 2/ }).click();
  await expect(page.getByText("0 conflicts", { exact: true })).toBeVisible();
  await expect(cell(1, p2).getByRole("button", { name: /^SCI/ })).toBeVisible();

  // Pinned classes cannot be dragged away.
  await selected.getByLabel(/^Pinned/).click(); // saved on the server before it shows as ticked
  await expect(cell(1, p2).getByRole("button", { name: "SCI, Mon Period 2, pinned" })).toBeVisible();
  await expect(selected.getByRole("button", { name: "Remove from timetable" })).toBeDisabled();

  // --- views by teacher and by room -----------------------------------------------
  await page.getByRole("button", { name: "By teacher" }).click();
  await page.getByRole("combobox", { name: "Teacher", exact: true }).selectOption({ label: "Ana Cruz" });
  await expect(cell(1, p1)).toContainText("11-A");
  await expect(cell(1, p2)).toContainText("11-B");
  await page.screenshot({ path: `${SHOTS}/11-timetable-by-teacher.png`, fullPage: true });
  await page.getByRole("button", { name: "By room" }).click();
  await page.getByRole("combobox", { name: "Room", exact: true }).selectOption({ label: "Room 1" });
  await expect(cell(1, p1)).toContainText("Ana Cruz");

  // --- export ---------------------------------------------------------------------
  for (const [button, extension] of [["Export Excel", "xlsx"], ["Export PDF", "pdf"]] as const) {
    const [file] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: button }).click()]);
    expect(file.suggestedFilename()).toBe(`timetable-Room-1.${extension}`);
  }

  // --- audit log of schedule changes ------------------------------------------------
  await page.getByRole("link", { name: "Change history" }).click();
  await expect(page.getByRole("cell", { name: "11-B · SCI: Mon Period 1 → Mon Period 2" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "11-A · MATH placed on Mon Period 1 in Room 1" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Timetable by room exported as PDF" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/12-change-history.png`, fullPage: true });
});

test("timetable fits a phone and is read-only for the teacher role", async ({ page, request }) => {
  const login = await request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const created = await request.post(`${API}/api/users`, {
    headers,
    data: { email: "viewer@timetable.example", full_name: "Viewer Teacher", password: PASSWORD, role: "teacher" },
  });
  expect(created.status()).toBe(201);

  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/login");
  await page.getByLabel("Email").fill("viewer@timetable.example");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.getByRole("link", { name: "Change history" })).toHaveCount(0);
  await page.getByRole("link", { name: "Timetable" }).click();

  const math = page.getByRole("button", { name: "MATH, Mon Period 1" });
  await expect(math).toBeVisible();
  await expect(math).toHaveAttribute("draggable", "false");
  await math.click();
  await expect(page.getByRole("region", { name: "Selected class" })).toContainText("Room: Room 1");
  await expect(page.getByRole("button", { name: "Remove from timetable" })).toHaveCount(0);
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflows).toBe(false);
  await page.screenshot({ path: `${SHOTS}/13-mobile-timetable.png` });
});
