import { expect, test } from "@playwright/test";

import { API, PASSWORD, setUpSchool } from "./setup";

const SHOTS = "D:/Temp/shots";
const EMAIL = "admin@timetable.example";

test("load teachers, build a timetable by drag and drop, fix a conflict, switch views, export, see history", async ({
  page,
  request,
}) => {
  const { p1, p2 } = await setUpSchool(request, EMAIL, "Timetable Test School");

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
