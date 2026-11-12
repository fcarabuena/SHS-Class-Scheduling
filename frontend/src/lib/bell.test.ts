import { describe, expect, it } from "vitest";

import { errorMessage } from "./api";
import { fromMinutes, generateBellSchedule, toMinutes, validateBellSchedule } from "./bell";

describe("time helpers", () => {
  it("converts both HH:MM and HH:MM:SS", () => {
    expect(toMinutes("07:30")).toBe(450);
    expect(toMinutes("07:30:00")).toBe(450);
    expect(fromMinutes(450)).toBe("07:30");
    expect(fromMinutes(0)).toBe("00:00");
  });
});

describe("generateBellSchedule", () => {
  it("creates back-to-back periods with one break", () => {
    const rows = generateBellSchedule({
      start: "07:00",
      periodMinutes: 60,
      periodCount: 4,
      breakAfter: 2,
      breakMinutes: 20,
      breakName: "Recess",
    });
    expect(rows.map((r) => `${r.name} ${r.start_time}-${r.end_time}`)).toEqual([
      "Period 1 07:00-08:00",
      "Period 2 08:00-09:00",
      "Recess 09:00-09:20",
      "Period 3 09:20-10:20",
      "Period 4 10:20-11:20",
    ]);
    expect(rows.filter((r) => r.is_break)).toHaveLength(1);
  });

  it("adds no break when breakAfter is 0 or after the last period", () => {
    const base = { start: "13:00", periodMinutes: 45, periodCount: 3, breakMinutes: 15 };
    expect(generateBellSchedule({ ...base, breakAfter: 0 })).toHaveLength(3);
    expect(generateBellSchedule({ ...base, breakAfter: 3 })).toHaveLength(3);
  });
});

describe("validateBellSchedule", () => {
  const row = (name: string, start_time: string, end_time: string, is_break = false) => ({
    name,
    start_time,
    end_time,
    is_break,
  });

  it("accepts a generated schedule that fits the shift", () => {
    const rows = generateBellSchedule({ start: "07:00", periodMinutes: 60, periodCount: 5, breakAfter: 2, breakMinutes: 20 });
    expect(validateBellSchedule(rows, "07:00", "12:30")).toBeNull();
  });

  it("reports overlaps, shift bounds and missing class periods", () => {
    expect(validateBellSchedule([row("A", "07:00", "08:00"), row("B", "07:30", "08:30")], "07:00", "12:00")).toMatch(/overlaps/);
    expect(validateBellSchedule([row("A", "06:30", "07:30")], "07:00", "12:00")).toMatch(/before the shift/);
    expect(validateBellSchedule([row("A", "11:30", "12:30")], "07:00", "12:00")).toMatch(/after the shift/);
    expect(validateBellSchedule([row("A", "09:00", "08:00")], "07:00", "12:00")).toMatch(/end after/);
    expect(validateBellSchedule([row("Recess", "09:00", "09:20", true)], "07:00", "12:00")).toMatch(/at least one/);
    expect(validateBellSchedule([row(" ", "07:00", "08:00")], "07:00", "12:00")).toMatch(/needs a name/);
  });
});

describe("errorMessage", () => {
  it("uses a plain detail string", () => {
    expect(errorMessage({ detail: "Incorrect email or password." }, "x")).toBe("Incorrect email or password.");
  });

  it("flattens FastAPI validation errors", () => {
    const body = {
      detail: [
        { loc: ["body", "capacity"], msg: "Input should be greater than 0" },
        { loc: ["body"], msg: "Value error, end_time must be after start_time" },
      ],
    };
    expect(errorMessage(body, "x")).toBe(
      "capacity: Input should be greater than 0; end_time must be after start_time",
    );
  });

  it("falls back when the body has no detail", () => {
    expect(errorMessage(null, "Request failed (500)")).toBe("Request failed (500)");
    expect(errorMessage({ other: 1 }, "fallback")).toBe("fallback");
  });
});
