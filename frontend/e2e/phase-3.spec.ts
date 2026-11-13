import { expect, test, type Page } from "@playwright/test";

import { API, PASSWORD, setUpSchool } from "./setup";

const SHOTS = "D:/Temp/shots";
const OWNER = "owner@platform.example"; // the platform admin, set in tests/e2e_server.py

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("share a timetable publicly, notify the teacher, and manage schools as the platform admin", async ({ page, browser, request }) => {
  const { p1, send, headers } = await setUpSchool(request, OWNER, "Operator Test School");
  const teachers = await (await request.get(`${API}/api/teachers`, { headers })).json();
  const ana = teachers.find((t: { full_name: string }) => t.full_name === "Ana Cruz");
  await send("post", "/api/users", {
    email: "ana@operator.example",
    full_name: "Ana Cruz",
    password: PASSWORD,
    role: "teacher",
    teacher_id: ana.id,
  });
  const loaded = await send("post", "/api/assignments/generate", {});
  const math = loaded.assignments[0]; // 11-A MATH
  await send("put", `/api/assignments/${math.id}`, { teacher_id: ana.id });
  await send("post", "/api/schedule/entries", { assignment_id: math.id, day_of_week: 1, period_id: p1 });

  // --- public share link ------------------------------------------------------------------
  await signIn(page, OWNER);
  await expect(page.getByText(/Plan:\s*Standard/)).toBeVisible();
  await page.getByRole("link", { name: "Edit times" }).click(); // straight to the bell schedule
  await expect(page.getByRole("heading", { name: "Step 4 of 5: Bell schedule" })).toBeVisible();
  await page.getByRole("button", { name: "Back to dashboard" }).click();
  await page.getByRole("link", { name: "Timetable" }).click();
  await page.getByRole("button", { name: "Share link" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Create link" }).click();
  const url = await dialog.getByLabel("Share link").inputValue();
  expect(url).toMatch(/^http:\/\/localhost:3001\/share\/[\w-]{40,}$/);
  await expect(dialog.getByRole("img", { name: "QR code of the link to 11-A" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/19-share-dialog.png`, fullPage: true });

  // A stranger with no session. Headless Chromium has no notification support and always reports
  // "denied"; make it report "default", the state a real phone starts in, before the student is asked.
  const visitor = await browser.newContext();
  await visitor.addInitScript(() => Object.defineProperty(Notification, "permission", { get: () => "default" }));
  const publicPage = await visitor.newPage();
  await publicPage.goto(url);
  await expect(publicPage.getByRole("heading", { name: "11-A" })).toBeVisible();
  await expect(publicPage.getByText("Operator Test School")).toBeVisible();
  await expect(publicPage.getByRole("cell", { name: /MATH\s*Ana Cruz/ })).toBeVisible();
  await expect(publicPage.getByRole("link", { name: "Dashboard" })).toHaveCount(0);
  await expect(publicPage.getByRole("button", { name: "Follow: notify me of changes" })).toBeVisible();
  const calendar = await publicPage.getByRole("link", { name: "Add to phone calendar" }).getAttribute("href");
  expect(calendar).toMatch(/^webcal:\/\/localhost:8001\/api\/public\/timetable\/[\w-]+\/calendar\.ics$/);
  expect(await (await request.get(calendar!.replace("webcal:", "http:"))).text()).toContain("SUMMARY:MATH");
  await publicPage.screenshot({ path: `${SHOTS}/20-public-timetable.png`, fullPage: true });

  await dialog.getByRole("button", { name: "Turn off" }).click();
  await expect(dialog.getByText("No links for this timetable yet.")).toBeVisible();
  await publicPage.reload();
  await expect(publicPage.getByText("This link does not exist or is no longer active.")).toBeVisible();
  await visitor.close();
  await dialog.getByRole("button", { name: "Close" }).click();

  // --- platform admin -------------------------------------------------------------------------
  const other = await request.post(`${API}/api/auth/register`, {
    data: { school_name: "Second Test School", full_name: "Second Admin", email: "admin@second.example", password: PASSWORD },
  });
  expect(other.status()).toBe(201);
  await page.getByRole("link", { name: "All schools" }).click();
  await expect(page.getByRole("heading", { name: "All schools" })).toBeVisible();
  page.once("dialog", (confirm) => confirm.accept());
  await page.getByRole("button", { name: "Suspend Second Test School" }).click();
  await expect(page.getByRole("button", { name: "Reactivate Second Test School" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Suspend Operator Test School" })).toHaveCount(0); // never your own
  await page.screenshot({ path: `${SHOTS}/21-all-schools.png`, fullPage: true });
  const blocked = await request.post(`${API}/api/auth/login`, { data: { email: "admin@second.example", password: PASSWORD } });
  expect(blocked.status()).toBe(403);

  // --- automatic teacher loading ---------------------------------------------------------------
  await page.getByRole("link", { name: "Teacher loading" }).click();
  await page.getByRole("button", { name: "Auto-assign teachers" }).click();
  await expect(page.getByText("Assigned a teacher to 3 subjects.")).toBeVisible();
  await expect(page.getByText("0 of 4 without a teacher")).toBeVisible();

  // --- the teacher's notifications -------------------------------------------------------------
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "ana@operator.example");
  await expect(page.getByRole("link", { name: /Notifications\s*2 unread/ })).toBeVisible();
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByText("You were given a class")).toBeVisible();
  await expect(page.getByText("Your timetable changed")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/22-notifications.png`, fullPage: true });
  await page.getByRole("button", { name: "Mark all as read" }).click();
  await expect(page.getByRole("link", { name: "Notifications", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "All schools" })).toHaveCount(0);
});
