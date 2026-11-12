import { expect, test } from "@playwright/test";

const SHOTS = "D:/Temp/shots";
const PASSWORD = "Str0ng-Passw0rd!";

test("register a school, finish setup, manage data, and check the read-only teacher role", async ({ page }) => {
  // --- register -------------------------------------------------------------
  await page.goto("/register");
  await page.getByLabel("School name").fill("Sample Senior High School");
  await page.getByLabel("Your full name").fill("Sample Admin");
  await page.getByLabel("Email").fill("admin@sample.example");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create school workspace" }).click();

  // --- onboarding wizard ----------------------------------------------------
  await expect(page.getByRole("heading", { name: "Step 1 of 5: School" })).toBeVisible();
  await page.getByLabel("Schools Division").fill("Sample Division");
  await page.screenshot({ path: `${SHOTS}/1-wizard-school.png`, fullPage: true });
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page.getByRole("heading", { name: "Step 2 of 5: School year" })).toBeVisible();
  await page.getByLabel("First day of classes").fill("2026-06-15");
  await page.getByLabel("Last day of classes").fill("2027-03-31");
  await page.getByRole("group", { name: "First semester" }).getByLabel("Ends").fill("2026-10-30");
  await page.getByRole("group", { name: "Second semester" }).getByLabel("Starts").fill("2026-11-09");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page.getByRole("heading", { name: "Step 3 of 5: Shifts" })).toBeVisible();
  await page.getByRole("button", { name: "Start with: double shift" }).click();
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page.getByRole("heading", { name: "Step 4 of 5: Bell schedule" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  for (const shift of ["Morning", "Afternoon"]) {
    const editor = page.locator("section", { has: page.getByRole("heading", { name: shift }) });
    await editor.getByRole("button", { name: "Generate" }).click();
    await editor.getByRole("button", { name: `Save ${shift} schedule` }).click();
    await expect(editor.getByText("saved", { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: `${SHOTS}/2-wizard-bell-schedule.png`, fullPage: true });
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Step 5 of 5: Strands" })).toBeVisible();
  await page.getByLabel(/^STEM/).check();
  await page.getByLabel(/^ABM/).check();
  await page.getByRole("button", { name: "Add 2 strands and finish" }).click();

  // --- dashboard ------------------------------------------------------------
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Sample Senior High School" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Strands/ }).filter({ hasText: "2" })).toBeVisible();
  await expect(page.getByText("Period 5").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/3-dashboard.png`, fullPage: true });

  // --- rooms: manual add + CSV import ---------------------------------------
  await page.getByRole("link", { name: "Rooms" }).first().click();
  await page.getByRole("button", { name: "Add room" }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("Code").fill("R101");
  await dialog.getByLabel("Name").fill("Room 101");
  await dialog.getByLabel("Capacity").fill("45");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: "R101" })).toBeVisible();

  await page.getByRole("button", { name: "Import CSV / Excel" }).click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("File to import").setInputFiles({
    name: "rooms.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("code,capacity,name,type\nCL1,40,Computer Laboratory 1,computer lab\nBAD,0,Broken Room,lecture\n"),
  });
  await dialog.getByRole("button", { name: "Import", exact: true }).click();
  await expect(dialog.getByText("Import finished: 1 to add, 0 to update, 1 with problems.")).toBeVisible();
  await expect(dialog.getByText("Row 3:")).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).last().click();
  await expect(page.getByRole("cell", { name: "CL1" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/4-rooms.png`, fullPage: true });

  // --- teachers: qualifications + unavailable slot ---------------------------
  await page.getByRole("link", { name: "Teachers" }).first().click();
  await page.getByRole("button", { name: "Add teacher" }).click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("Employee ID").fill("T-0001");
  await dialog.getByLabel("Full name").fill("Sample Teacher");
  await dialog.getByLabel(/^CORE-GENMATH/).check();
  await dialog.getByRole("button", { name: "Mon Period 1: no preference" }).first().click();
  await page.screenshot({ path: `${SHOTS}/5-teacher-form.png`, fullPage: true });
  await dialog.getByRole("button", { name: "Save" }).click();
  const teacherRow = page.getByRole("row", { name: /T-0001/ });
  await expect(teacherRow).toContainText("6 h/day · 30 h/week"); // school defaults applied
  await expect(teacherRow).toContainText("CORE-GENMATH");
  await expect(teacherRow).toContainText("1 unavailable · 0 preferred");

  // --- sections ---------------------------------------------------------------
  await page.getByRole("link", { name: "Sections" }).first().click();
  await page.getByRole("button", { name: "Add section" }).click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("Section name").fill("11-STEM-A");
  await dialog.getByLabel("Strand").selectOption({ label: "STEM – Science, Technology, Engineering and Mathematics" });
  await dialog.getByLabel("Shift").selectOption({ label: "Morning" });
  await dialog.getByLabel("Adviser").selectOption({ label: "Sample Teacher" });
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: /11-STEM-A/ })).toContainText("Sample Teacher");

  // --- users: create a read-only teacher account ------------------------------
  await page.getByRole("link", { name: "User accounts" }).click();
  await page.getByRole("button", { name: "Add user" }).click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("Full name").fill("Sample Teacher");
  await dialog.getByLabel("Email").fill("teacher@sample.example");
  await dialog.getByLabel("Role").selectOption("teacher");
  await dialog.getByLabel("Password").fill(PASSWORD);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: "teacher@sample.example" })).toBeVisible();

  // --- teacher role is read-only ------------------------------------------------
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill("teacher@sample.example");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("link", { name: "User accounts" })).toHaveCount(0);

  await page.getByRole("link", { name: "Rooms" }).first().click();
  await expect(page.getByRole("cell", { name: "R101" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add room" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/6-teacher-read-only.png`, fullPage: true });
});

test("wrong password shows an error and protected pages redirect to sign in", async ({ page }) => {
  await page.goto("/subjects");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill("nobody@sample.example");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Incorrect email or password." })).toBeVisible();
});

test("layout works at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@sample.example");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("link", { name: "Subjects" }).click();
  await expect(page.getByRole("heading", { name: "Subjects" })).toBeVisible();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflows).toBe(false);
  await page.screenshot({ path: `${SHOTS}/7-mobile-subjects.png` });
});
