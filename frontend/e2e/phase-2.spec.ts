import { expect, test } from "@playwright/test";

import { API, PASSWORD, setUpSchool } from "./setup";

const SHOTS = "D:/Temp/shots";
const EMAIL = "admin@auto.example";

type Assignment = { id: number; section_id: number; subject_id: number };

test("auto-schedule around a pinned class, then check the dashboard and the substitute finder", async ({ page, request }) => {
  const { p1, send, headers } = await setUpSchool(request, EMAIL, "Auto Schedule School");

  // Teacher loading through the API: Ben teaches MATH, Ana teaches SCI.
  const loaded = await send("post", "/api/assignments/generate", {});
  const lists = await Promise.all(
    ["subjects", "teachers", "sections"].map(async (name) => (await request.get(`${API}/api/${name}`, { headers })).json()),
  );
  const [subjects, teachers, sections] = lists;
  const idOf = (rows: { id: number }[], key: string, value: string) =>
    (rows as unknown as Record<string, unknown>[]).find((row) => row[key] === value)!.id as number;
  const sci = idOf(subjects, "code", "SCI");
  const ana = idOf(teachers, "full_name", "Ana Cruz");
  const ben = idOf(teachers, "full_name", "Ben Reyes");
  for (const assignment of loaded.assignments as Assignment[]) {
    await send("put", `/api/assignments/${assignment.id}`, { teacher_id: assignment.subject_id === sci ? ana : ben });
  }
  // Pin 11-A Science on Monday period 1; the scheduler must build around it.
  const sectionA = idOf(sections, "name", "11-A");
  const target = (loaded.assignments as Assignment[]).find((a) => a.section_id === sectionA && a.subject_id === sci)!;
  const placed = await send("post", "/api/schedule/entries", { assignment_id: target.id, day_of_week: 1, period_id: p1 });
  await send("put", `/api/schedule/entries/${placed.entry_id}`, { pinned: true });

  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("link", { name: /13%\s*of class hours placed/ })).toBeVisible(); // 1 h of 8 h

  // --- automatic scheduling ---------------------------------------------------------
  await page.getByRole("link", { name: "Timetable" }).click();
  await page.getByRole("button", { name: "Auto-schedule" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Rebuild the timetable")).toBeChecked();
  await dialog.getByLabel("Time limit (seconds)").fill("5");
  await dialog.getByRole("button", { name: "Start" }).click();
  await expect(dialog.getByText("Every class fits: 8 h placed with no conflicts.")).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByText(/Applying this adds 7 classes, keeps 1 and removes 0/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/14-auto-schedule-result.png`, fullPage: true });

  // Nothing is saved until it is applied.
  await expect(page.getByText("4 subjects short of hours")).toBeVisible();
  await dialog.getByRole("button", { name: "Apply this timetable" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("0 conflicts", { exact: true })).toBeVisible();
  await expect(page.getByText("0 subjects short of hours")).toBeVisible();
  await expect(page.locator(`[data-cell="1:${p1}"]`).getByRole("button", { name: "SCI, Mon Period 1, pinned" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Weekly timetable of 11-A" }).getByRole("button", { name: /^(MATH|SCI),/ })).toHaveCount(4);
  await page.screenshot({ path: `${SHOTS}/15-auto-schedule-applied.png`, fullPage: true });

  // --- remarks on a class, signatories on printouts ------------------------------------
  const pinnedClass = page.locator(`[data-cell="1:${p1}"]`).getByRole("button", { name: /^SCI/ });
  await pinnedClass.click();
  const panel = page.getByRole("region", { name: "Selected class" });
  await panel.getByLabel("Remarks").fill("Bring lab gown");
  await panel.getByLabel("Remarks").press("Enter");
  await expect(pinnedClass).toContainText("Bring lab gown");

  await page.getByRole("button", { name: "Signatories" }).click();
  const signing = page.getByRole("dialog");
  await signing.getByLabel("Signatory 1 name").fill("Maria Santos");
  await signing.getByLabel("Signatory 1 position").fill("Class Program Coordinator");
  await signing.getByRole("button", { name: "Remove signatory 2" }).click();
  await page.screenshot({ path: `${SHOTS}/18-signatories.png`, fullPage: true });
  await signing.getByRole("button", { name: "Save signatories" }).click();
  await expect(signing).toHaveCount(0);
  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export PDF" }).click()]);
  expect(pdf.suggestedFilename()).toBe("timetable-11-A.pdf");
  await pdf.saveAs("D:/Temp/shots/timetable-11-A.pdf");
  await page.getByRole("button", { name: "Signatories" }).click();
  await expect(page.getByRole("dialog").getByLabel("Signatory 1 name")).toHaveValue("Maria Santos");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

  // --- dashboard ----------------------------------------------------------------------
  await page.getByRole("link", { name: "Dashboard" }).click();
  const summary = page.getByRole("region", { name: "Schedule summary" });
  await expect(summary.getByRole("link", { name: /100%\s*of class hours placed/ })).toBeVisible();
  await expect(summary.getByRole("link", { name: /0\s*conflicts to fix/ })).toBeVisible();
  await expect(summary.getByText("No conflicts and no subject short of hours.")).toBeVisible();
  await expect(summary.getByRole("listitem").filter({ hasText: "11-A" })).toContainText("4 h of 4 h · 100%");
  await expect(summary.getByRole("listitem").filter({ hasText: "Ana Cruz" })).toContainText("4 h of 30 h · 13%");
  await page.screenshot({ path: `${SHOTS}/16-dashboard.png`, fullPage: true });

  // --- substitute finder -----------------------------------------------------------------
  await page.getByRole("link", { name: "Find a substitute" }).click();
  await page.getByLabel("Absent teacher").selectOption({ label: "Ana Cruz" });
  await page.getByLabel("Day").selectOption({ label: "Mon" });
  const lesson = page.getByRole("region", { name: "Period 1 · SCI · 11-A" });
  await expect(lesson).toBeVisible();
  await expect(lesson).toContainText(/Ben Reyes|Nobody is free at this time/);
  await page.screenshot({ path: `${SHOTS}/17-substitutes.png`, fullPage: true });

  // The run is in the change history.
  await page.getByRole("link", { name: "Change history" }).click();
  await expect(page.getByRole("cell", { name: "Generated timetable applied: 7 class(es) placed, 0 replaced, 1 kept" })).toBeVisible();
});
