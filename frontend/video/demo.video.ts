import { expect, test, type Locator, type Page } from "@playwright/test";

const OUT = "D:/Projects/shs-scheduler/demo-video/shs-scheduler-demo.webm";
const SHOTS = "D:/Temp/video-shots";

type Overlay = Window & {
  __caption: (title: string, text: string) => void;
  __card: (title: string, lines: string[]) => void;
};

/** Caption bar and title cards, drawn on top of the app in its own colours. Re-added after each page load. */
function installOverlay() {
  const w = window as unknown as Overlay;
  const box = (id: string) => {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      document.documentElement.appendChild(el);
    }
    return el;
  };
  w.__caption = (title, text) => {
    const el = box("demo-caption");
    Object.assign(el.style, {
      position: "fixed",
      left: "50%",
      bottom: "22px",
      transform: "translateX(-50%)",
      width: "min(980px, 92vw)",
      zIndex: "2147483646",
      background: "rgba(26, 56, 112, 0.96)",
      borderTop: "5px solid #e3112b",
      color: "#ffffff",
      padding: "14px 22px 16px",
      fontFamily: "'IBM Plex Sans', 'Segoe UI', sans-serif",
      boxShadow: "0 8px 30px rgba(0,0,0,.35)",
      display: title || text ? "block" : "none",
    });
    el.innerHTML =
      `<div style="font-size:23px;font-weight:600;line-height:1.25">${title}</div>` +
      (text ? `<div style="margin-top:6px;font-size:17px;line-height:1.4;color:#dce6f6">${text}</div>` : "");
  };
  w.__card = (title, lines) => {
    const el = box("demo-card");
    Object.assign(el.style, {
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      background: "linear-gradient(160deg, #21468b 0%, #142b57 100%)",
      borderTop: "8px solid #e3112b",
      color: "#ffffff",
      display: title ? "flex" : "none",
      flexDirection: "column",
      justifyContent: "center",
      alignItems: "center",
      textAlign: "center",
      fontFamily: "'IBM Plex Sans', 'Segoe UI', sans-serif",
      padding: "40px",
    });
    el.innerHTML =
      `<div style="font-size:16px;letter-spacing:.18em;text-transform:uppercase;color:#84c5f3">Senior High School</div>` +
      `<div style="margin-top:14px;font-size:46px;font-weight:600;line-height:1.15;max-width:1000px">${title}</div>` +
      lines.map((line) => `<div style="margin-top:14px;font-size:22px;color:#dce6f6;max-width:900px">${line}</div>`).join("");
  };
}

async function caption(page: Page, title: string, text = "", holdMs = 0) {
  await page.evaluate(([t, x]) => (window as unknown as Overlay).__caption(t, x), [title, text]);
  if (holdMs) await page.waitForTimeout(holdMs);
}

async function card(page: Page, title: string, lines: string[], holdMs: number) {
  await page.evaluate(([t, l]) => (window as unknown as Overlay).__card(t as string, l as string[]), [title, lines] as const);
  await page.waitForTimeout(holdMs);
  await page.evaluate(() => (window as unknown as Overlay).__card("", []));
}

/** Draws attention to one element for a moment. */
async function spotlight(target: Locator, holdMs = 2200) {
  await target.evaluate((el: HTMLElement) => {
    el.scrollIntoView({ block: "center" }); // keeps it clear of the caption bar at the bottom
    el.dataset.demoOutline = el.style.outline;
    el.style.outline = "4px solid #fcd116";
    el.style.outlineOffset = "3px";
    el.style.boxShadow = "0 0 0 10px rgba(33, 70, 139, 0.28)";
  });
  await target.page().waitForTimeout(holdMs);
  await target.evaluate((el: HTMLElement) => {
    el.style.outline = el.dataset.demoOutline ?? "";
    el.style.boxShadow = "";
  });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

test("demo video: from an empty week to a conflict-free timetable", async ({ page, context }) => {
  await context.addInitScript(installOverlay);
  // Headless Chromium always reports notifications as "denied"; a real phone starts at "default".
  await context.addInitScript(() => Object.defineProperty(Notification, "permission", { get: () => "default" }));

  // --- opening ---------------------------------------------------------------------------------
  await page.goto("/login");
  await card(
    page,
    "Class Scheduling &amp; Teacher Loading System",
    ["Conflict-free timetables in minutes, not weeks", "Built for Philippine DepEd Senior High Schools"],
    4500,
  );
  await caption(page, "Each school gets its own private workspace", "Admins, schedulers and teachers sign in with their own roles.");
  await page.getByLabel("Email").pressSequentially("admin@demo.example", { delay: 35 });
  await page.getByLabel("Password").pressSequentially("DemoPass#2026", { delay: 35 });
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // --- dashboard -------------------------------------------------------------------------------
  await caption(page, "The dashboard shows the whole school at a glance", "Sections, teachers and rooms are entered once, or imported from Excel.", 3200);
  await spotlight(page.getByRole("region", { name: "Schedule summary" }).getByRole("link").first(), 2600);
  await caption(page, "Nothing is scheduled yet: 0% of class hours placed", "Let's build this semester's timetable for four sections.", 3000);
  await shot(page, "01-dashboard-empty");

  // --- bell schedule ---------------------------------------------------------------------------
  await caption(page, "Your own bell schedule", "Periods can start at any minute, like 7:30, and recess and lunch are breaks.");
  await page.getByRole("link", { name: "Edit times" }).click();
  await expect(page.getByRole("heading", { name: "Step 4 of 5: Bell schedule" })).toBeVisible();
  await page.waitForTimeout(800);
  await spotlight(page.locator("section").filter({ has: page.getByRole("heading", { name: /Regular/ }) }).locator("table"), 3800);
  await shot(page, "02-bell-schedule");
  await page.getByRole("button", { name: "Back to dashboard" }).click();

  // --- teacher loading -------------------------------------------------------------------------
  await page.getByRole("link", { name: "Teacher loading" }).click();
  await caption(page, "Teacher loading, step 1: subjects come from the DepEd curriculum", "One click lists every subject each section must take this semester.");
  await page.waitForTimeout(1500);
  const addSubjects = page.getByRole("button", { name: "Add subjects from curriculum" });
  await spotlight(addSubjects, 1500);
  await addSubjects.click();
  await expect(page.getByText("Added 36 subjects from the curriculum.")).toBeVisible();
  await page.waitForTimeout(1800);
  await caption(
    page,
    "Step 2: one click assigns a qualified teacher to every subject",
    "It picks the least-loaded teacher who still has room within the daily and weekly load limits.",
  );
  const autoAssign = page.getByRole("button", { name: "Auto-assign teachers" });
  await spotlight(autoAssign, 1500);
  await autoAssign.click();
  await expect(page.getByText("Assigned a teacher to 36 subjects.")).toBeVisible();
  await page.waitForTimeout(1200);
  await caption(page, "Every teacher's load is checked live", "Bars turn amber when someone is over a limit or not qualified. Here, everyone is within limits.");
  await spotlight(page.getByRole("region", { name: "Teacher loads" }), 4200);
  await shot(page, "03-teacher-loading");

  // --- auto-schedule ---------------------------------------------------------------------------
  await page.getByRole("link", { name: "Timetable" }).click();
  await caption(page, "Auto-schedule builds the whole week", "No teacher, room or section is ever double-booked, and every hour the curriculum requires is placed.");
  await page.waitForTimeout(1500);
  const auto = page.getByRole("button", { name: "Auto-schedule" });
  await spotlight(auto, 1500);
  await auto.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Time limit (seconds)").fill("10");
  await page.waitForTimeout(1200);
  await dialog.getByRole("button", { name: "Start" }).click();
  await caption(page, "Working…", "It searches thousands of possible timetables and keeps the best one.");
  await expect(dialog.getByText(/Every class fits/)).toBeVisible({ timeout: 60_000 });
  await caption(page, "Done: every class fits, with zero conflicts", "You review the result first. Nothing changes until you apply it.");
  await spotlight(dialog.getByText(/Every class fits/), 3000);
  await shot(page, "04-auto-schedule-result");
  await dialog.getByRole("button", { name: "Apply this timetable" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("0 conflicts", { exact: true })).toBeVisible();

  // --- the timetable ---------------------------------------------------------------------------
  const grid = page.getByRole("table", { name: /Weekly timetable of/ });
  await caption(page, "The finished weekly timetable", "Each class shows its subject, teacher and room.", 3500);
  await shot(page, "05-timetable");
  const firstClass = grid.getByRole("button").first();
  await caption(page, "Click or drag any class to move it", "Green slots are safe, red ones would cause a conflict, and the check is live as you move.");
  await firstClass.click();
  await page.waitForTimeout(3800);
  await shot(page, "06-drop-targets");

  // --- conflicts and suggested fixes -----------------------------------------------------------
  const selected = page.getByRole("region", { name: "Selected class" });
  await caption(page, "Break a rule, and it is caught at once", "Here the class is moved into the covered court, the wrong kind of room for it.");
  const roomSelect = selected.getByLabel("Room");
  await spotlight(roomSelect, 1200);
  const court = await roomSelect.locator("option", { hasText: "Covered Court" }).getAttribute("value");
  await roomSelect.selectOption(court!);
  await expect(page.getByText("1 conflict", { exact: true })).toBeVisible();
  await caption(page, "The system explains the problem and suggests fixes", "Each fix is checked against every rule. Apply one with a single click.");
  await spotlight(selected.getByRole("heading", { name: "Suggested fixes" }).locator(".."), 3500);
  await shot(page, "07-suggested-fixes");
  await selected.getByRole("button", { name: /^Use / }).first().click();
  await expect(page.getByText("0 conflicts", { exact: true })).toBeVisible();
  await caption(page, "Fixed: back to zero conflicts", "", 2500);
  await page.getByRole("button", { name: "Close selected class" }).click();

  // --- views and exports -----------------------------------------------------------------------
  await caption(page, "Every timetable three ways: by section, by teacher, by room", "Teachers see exactly where they need to be.");
  await page.getByRole("button", { name: "By teacher" }).click();
  await page.waitForTimeout(3200);
  await shot(page, "08-by-teacher");
  await page.getByRole("button", { name: "By room" }).click();
  await page.waitForTimeout(2600);
  await page.getByRole("button", { name: "By section" }).click();
  await caption(page, "Print-ready PDF and Excel", "For one section or all of them, with the school's signatories at the bottom.");
  const pdf = page.getByRole("button", { name: "Export PDF" });
  await spotlight(pdf, 1600);
  await Promise.all([page.waitForEvent("download"), pdf.click()]);
  await page.waitForTimeout(1500);

  // --- students ----------------------------------------------------------------------------------
  await caption(page, "Share with students: no accounts, no personal data", "Each section gets a link and a QR code to post in the classroom.");
  await page.getByRole("button", { name: "Share link" }).click();
  const share = page.getByRole("dialog");
  await share.getByRole("button", { name: "Create link" }).click();
  await expect(share.getByRole("img", { name: /QR code/ })).toBeVisible();
  await spotlight(share.getByRole("img", { name: /QR code/ }), 3500);
  await shot(page, "09-share-qr");
  const url = await share.getByLabel("Share link").inputValue();
  await page.goto(url);
  await expect(page.getByRole("button", { name: "Follow: notify me of changes" })).toBeVisible();
  await caption(page, "What a student sees after scanning", "Their section's timetable, always up to date. Tap Follow to get a phone notification whenever it changes.");
  await spotlight(page.getByRole("region", { name: "Follow this timetable" }), 4200);
  await caption(page, "Or add it to the phone's calendar", "Every class appears in the calendar for the whole semester.");
  await spotlight(page.getByRole("link", { name: "Add to phone calendar" }), 3000);
  await shot(page, "10-student-page");

  // --- substitutes -------------------------------------------------------------------------------
  await page.goto("/substitutes");
  await caption(page, "A teacher is absent?", "See at once who is free, qualified and within their load to cover each class.");
  await page.getByLabel("Absent teacher").selectOption({ index: 1 });
  await page.getByLabel("Day").selectOption({ label: "Mon" });
  await expect(page.getByRole("region").first()).toBeVisible();
  await page.waitForTimeout(4500);
  await shot(page, "11-substitutes");

  // --- closing -----------------------------------------------------------------------------------
  await page.goto("/dashboard");
  await caption(page, "From an empty week to a complete timetable in a few minutes", "100% of class hours placed, zero conflicts, every teacher within limits.");
  await spotlight(page.getByRole("region", { name: "Schedule summary" }), 4500);
  await shot(page, "12-dashboard-done");
  await caption(page, "", "");
  await card(
    page,
    "Class Scheduling &amp; Teacher Loading System",
    [
      "Automatic · Conflict-free · DepEd curriculum built in",
      "No student personal data (RA 10173) · Every change logged",
      "Runs free on Vercel, Render and Neon",
    ],
    6000,
  );

  await page.close();
  await page.video()!.saveAs(OUT);
});
