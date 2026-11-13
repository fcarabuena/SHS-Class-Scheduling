"""Teacher loading, timetable editing, conflicts, export and audit through the API."""

import io
import time

import pytest
from openpyxl import load_workbook

from .conftest import Api, add_user

MON, TUE, SAT = 1, 2, 6


@pytest.fixture
def world(admin, school_setup) -> dict:
    """Two sections, three subjects, two teachers, rooms, and a curriculum."""
    strand, shift = school_setup["strand"], school_setup["shift"]
    periods = [p for p in shift["periods"] if not p["is_break"]]
    math = admin.create("/api/subjects", code="MATH", name="Mathematics", type="core", hours_per_week=2)
    sci = admin.create("/api/subjects", code="SCI", name="Science", type="core", hours_per_week=2)
    ict = admin.create(
        "/api/subjects", code="ICT", name="Computer", type="applied", hours_per_week=1, required_room_type="computer_lab"
    )
    ana = admin.create(
        "/api/teachers", employee_id="T-1", full_name="Ana Cruz", qualified_subject_ids=[math["id"], sci["id"], ict["id"]]
    )
    ben = admin.create("/api/teachers", employee_id="T-2", full_name="Ben Reyes", qualified_subject_ids=[math["id"]])
    room1 = admin.create("/api/rooms", code="R1", name="Room 1", capacity=45)
    room2 = admin.create("/api/rooms", code="R2", name="Room 2", capacity=45)
    lab = admin.create("/api/rooms", code="LAB", name="Computer Lab", type="computer_lab", capacity=45)
    sec_a = admin.create("/api/sections", name="11-A", strand_id=strand["id"], grade_level=11, shift_id=shift["id"], student_count=40)
    sec_b = admin.create("/api/sections", name="11-B", strand_id=strand["id"], grade_level=11, shift_id=shift["id"], student_count=40)
    for subject in (math, sci, ict):
        admin.create("/api/curriculum", strand_id=strand["id"], subject_id=subject["id"], grade_level=11, semester_number=1)
    semester = school_setup["year"]["semesters"][0]
    return {
        "semester": semester,
        "shift": shift,
        "periods": periods,
        "break": next(p for p in shift["periods"] if p["is_break"]),
        "math": math,
        "sci": sci,
        "ict": ict,
        "ana": ana,
        "ben": ben,
        "room1": room1,
        "room2": room2,
        "lab": lab,
        "a": sec_a,
        "b": sec_b,
    }


def ok(response, status=200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def generate(api: Api) -> dict:
    return ok(api.post("/api/assignments/generate", json={}))


def assignment(data: dict, section: dict, subject: dict) -> dict:
    return next(a for a in data["assignments"] if (a["section_id"], a["subject_id"]) == (section["id"], subject["id"]))


def assign(api: Api, data: dict, section: dict, subject: dict, teacher: dict | None) -> dict:
    row = assignment(data, section, subject)
    return ok(api.put(f"/api/assignments/{row['id']}", json={"teacher_id": teacher["id"] if teacher else None}))


def place(api: Api, data: dict, section: dict, subject: dict, day: int, period: dict, **extra):
    row = assignment(data, section, subject)
    return api.post(
        "/api/schedule/entries", json={"assignment_id": row["id"], "day_of_week": day, "period_id": period["id"], **extra}
    )


def entry_at(data: dict, section: dict, day: int, period: dict) -> dict | None:
    key = (section["id"], day, period["id"])
    return next((e for e in data["entries"] if (e["section_id"], e["day_of_week"], e["period_id"]) == key), None)


def codes(data: dict) -> set[str]:
    return {c["code"] for c in data["conflicts"]}


# --- teacher loading ----------------------------------------------------------


def test_generate_assignments_from_curriculum_is_repeatable(admin, world):
    first = generate(admin)
    assert first["created"] == 6 and len(first["assignments"]) == 6
    assert all(a["teacher_id"] is None and a["scheduled_hours"] == 0 for a in first["assignments"])
    assert generate(admin)["created"] == 0
    assert first["semester_id"] == world["semester"]["id"] and first["days"] == [1, 2, 3, 4, 5]


def test_required_hours_follow_the_curriculum_override(admin, world, school_setup):
    row = admin.get("/api/curriculum").json()[0]
    ok(admin.put(f"/api/curriculum/{row['id']}", json={**row, "hours_per_week": 5}))
    data = generate(admin)
    hours = {a["required_hours"] for a in data["assignments"] if a["subject_id"] == row["subject_id"]}
    assert hours == {5}


def test_assigning_a_teacher_updates_the_load(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    data = assign(admin, data, world["b"], world["math"], world["ana"])
    load = next(x for x in data["teacher_loads"] if x["teacher_id"] == world["ana"]["id"])
    assert (load["assigned_hours"], load["max_weekly_hours"], load["max_daily_hours"], load["status"]) == (4, 30, 6, "ok")
    assert load["issues"] == []


def test_load_over_the_weekly_limit_and_unqualified_subject_are_flagged(admin, world):
    teacher = {**world["ben"], "max_daily_hours": 2, "max_weekly_hours": 3}
    ok(admin.put(f"/api/teachers/{teacher['id']}", json=teacher))
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ben"])
    data = assign(admin, data, world["b"], world["math"], world["ben"])
    data = assign(admin, data, world["a"], world["ict"], world["ben"])
    load = next(x for x in data["teacher_loads"] if x["teacher_id"] == world["ben"]["id"])
    assert load["status"] == "over" and load["assigned_hours"] == 5
    assert any("weekly limit is 3 h" in issue for issue in load["issues"])
    assert "Not qualified for: ICT." in load["issues"]


def test_manual_assignment_and_duplicate_is_rejected(admin, world):
    body = {"semester_id": world["semester"]["id"], "section_id": world["a"]["id"], "subject_id": world["math"]["id"]}
    data = ok(admin.post("/api/assignments", json={**body, "teacher_id": world["ana"]["id"]}), 201)
    assert len(data["assignments"]) == 1 and data["assignments"][0]["teacher_id"] == world["ana"]["id"]
    assert admin.post("/api/assignments", json=body).status_code == 409


# --- placing and moving classes -----------------------------------------------


def test_placing_a_class_picks_a_suitable_free_room(admin, world):
    data = generate(admin)
    p1 = world["periods"][0]
    data = ok(place(admin, data, world["a"], world["ict"], MON, p1), 201)
    assert entry_at(data, world["a"], MON, p1)["room_id"] == world["lab"]["id"]  # needs a computer lab
    data = ok(place(admin, data, world["b"], world["math"], MON, p1), 201)
    first_room = entry_at(data, world["b"], MON, p1)["room_id"]
    assert first_room in (world["room1"]["id"], world["room2"]["id"])
    # The lab is free again in period 2.
    data = ok(place(admin, data, world["b"], world["ict"], MON, world["periods"][1]), 201)
    assert entry_at(data, world["b"], MON, world["periods"][1])["room_id"] == world["lab"]["id"]
    assert assignment(data, world["a"], world["ict"])["scheduled_hours"] == 1
    assert "SUBJECT_HOURS_UNDER" in codes(data) and data["summary"]["errors"] == 0


def test_slot_rules_occupied_break_wrong_day_and_other_shift(admin, world):
    data = generate(admin)
    p1 = world["periods"][0]
    ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    assert place(admin, data, world["a"], world["sci"], MON, p1).status_code == 409
    assert place(admin, data, world["a"], world["sci"], MON, world["break"]).status_code == 422
    assert place(admin, data, world["a"], world["sci"], SAT, p1).status_code == 422

    afternoon = admin.create("/api/shifts", name="Afternoon", start_time="12:00", end_time="17:00")
    periods = [{"name": "Period 1", "start_time": "12:00", "end_time": "13:00"}]
    other = ok(admin.put(f"/api/shifts/{afternoon['id']}/periods", json=periods))["periods"][0]
    response = place(admin, data, world["a"], world["sci"], MON, other)
    assert response.status_code == 422 and "different shift" in response.json()["detail"]


def test_double_booking_is_detected_checked_and_fixed_by_a_suggestion(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    data = assign(admin, data, world["b"], world["sci"], world["ana"])
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)

    # Real-time check before dropping: Monday period 1 would double-book Ana.
    target = assignment(data, world["b"], world["sci"])
    cells = ok(admin.post("/api/schedule/check", json={"assignment_id": target["id"]}))["cells"]
    cell = {(c["day_of_week"], c["period_id"]): c for c in cells}
    assert cell[(MON, p1["id"])]["status"] == "conflict" and "Ana Cruz" in cell[(MON, p1["id"])]["messages"][0]
    assert cell[(MON, p2["id"])]["status"] == "ok"
    assert len(cells) == 5 * 3  # school days x teaching periods, breaks excluded

    data = ok(place(admin, data, world["b"], world["sci"], MON, p1), 201)
    assert "TEACHER_DOUBLE_BOOKED" in codes(data) and data["summary"]["errors"] == 1
    clash = entry_at(data, world["b"], MON, p1)

    found = ok(admin.get(f"/api/schedule/entries/{clash['id']}/suggestions"))
    assert "TEACHER_DOUBLE_BOOKED" in {c["code"] for c in found["conflicts"]}
    move = next(f for f in found["fixes"] if f["kind"] == "move")
    assert move["label"] == "Move to Monday Period 2"
    data = ok(admin.put(f"/api/schedule/entries/{clash['id']}", json={"day_of_week": move["day_of_week"], "period_id": move["period_id"]}))
    assert data["summary"]["errors"] == 0


def test_room_conflicts_and_changing_the_room(admin, world):
    data = generate(admin)
    p1 = world["periods"][0]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1, room_id=world["room1"]["id"]), 201)
    data = ok(place(admin, data, world["b"], world["math"], MON, p1, room_id=world["room1"]["id"]), 201)
    assert "ROOM_DOUBLE_BOOKED" in codes(data)
    second = entry_at(data, world["b"], MON, p1)
    fixes = ok(admin.get(f"/api/schedule/entries/{second['id']}/suggestions"))["fixes"]
    assert {"kind": "room", "room_id": world["room2"]["id"]}.items() <= next(f for f in fixes if f["kind"] == "room").items()
    data = ok(admin.put(f"/api/schedule/entries/{second['id']}", json={"room_id": world["lab"]["id"]}))
    assert codes(data) >= {"ROOM_TYPE_MISMATCH"} and "ROOM_DOUBLE_BOOKED" not in codes(data)
    data = ok(admin.put(f"/api/schedule/entries/{second['id']}", json={"room_id": None}))
    assert entry_at(data, world["b"], MON, p1)["room_id"] is None and data["summary"]["errors"] == 0


def test_moving_onto_an_occupied_slot_swaps_the_two_classes(admin, world):
    data = generate(admin)
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    data = ok(place(admin, data, world["a"], world["sci"], TUE, p2), 201)
    math_entry = entry_at(data, world["a"], MON, p1)

    cells = ok(admin.post("/api/schedule/check", json={"entry_id": math_entry["id"]}))["cells"]
    cell = {(c["day_of_week"], c["period_id"]): c for c in cells}
    assert cell[(MON, p1["id"])]["status"] == "current"
    assert cell[(TUE, p2["id"])]["swap"] is True and cell[(TUE, p2["id"])]["status"] == "ok"

    data = ok(admin.put(f"/api/schedule/entries/{math_entry['id']}", json={"day_of_week": TUE, "period_id": p2["id"]}))
    assert entry_at(data, world["a"], TUE, p2)["subject_id"] == world["math"]["id"]
    assert entry_at(data, world["a"], MON, p1)["subject_id"] == world["sci"]["id"]
    assert len(data["entries"]) == 2


def test_pinned_classes_cannot_be_moved_swapped_or_removed(admin, world):
    data = generate(admin)
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    data = ok(place(admin, data, world["a"], world["sci"], MON, p2), 201)
    pinned, other = entry_at(data, world["a"], MON, p1), entry_at(data, world["a"], MON, p2)
    data = ok(admin.put(f"/api/schedule/entries/{pinned['id']}", json={"pinned": True}))
    assert entry_at(data, world["a"], MON, p1)["pinned"] is True

    move = {"day_of_week": TUE, "period_id": p1["id"]}
    assert admin.put(f"/api/schedule/entries/{pinned['id']}", json=move).status_code == 409
    assert admin.put(f"/api/schedule/entries/{pinned['id']}", json={"room_id": None}).status_code == 409
    assert admin.delete(f"/api/schedule/entries/{pinned['id']}").status_code == 409
    swap = admin.put(f"/api/schedule/entries/{other['id']}", json={"day_of_week": MON, "period_id": p1["id"]})
    assert swap.status_code == 409 and "pinned" in swap.json()["detail"]
    cells = ok(admin.post("/api/schedule/check", json={"entry_id": pinned["id"]}))["cells"]
    assert {c["status"] for c in cells} == {"current", "blocked"}

    # Clearing the timetable keeps pinned classes.
    cleared = ok(admin.delete("/api/schedule"))
    assert cleared["removed"] == 1 and [e["id"] for e in cleared["entries"]] == [pinned["id"]]

    # Unpinning and moving can be done in one request.
    data = ok(admin.put(f"/api/schedule/entries/{pinned['id']}", json={"pinned": False, **move}))
    assert entry_at(data, world["a"], TUE, p1)["pinned"] is False
    assert ok(admin.delete(f"/api/schedule/entries/{pinned['id']}"))["entries"] == []


def test_changing_the_teacher_updates_scheduled_classes(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    p1 = world["periods"][0]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    assert entry_at(data, world["a"], MON, p1)["teacher_id"] == world["ana"]["id"]
    data = assign(admin, data, world["a"], world["math"], world["ben"])
    assert entry_at(data, world["a"], MON, p1)["teacher_id"] == world["ben"]["id"]
    data = assign(admin, data, world["a"], world["math"], None)
    assert entry_at(data, world["a"], MON, p1)["teacher_id"] is None


def test_unavailable_teacher_and_daily_limit_show_up_as_conflicts(admin, world):
    p1, p2, p3 = world["periods"]
    teacher = {**world["ana"], "max_daily_hours": 1, "availability": [{"day_of_week": TUE, "period_id": p1["id"], "kind": "unavailable"}]}
    ok(admin.put(f"/api/teachers/{teacher['id']}", json=teacher))
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    data = ok(place(admin, data, world["a"], world["math"], MON, p2), 201)
    assert "TEACHER_DAILY_OVERLOAD" in codes(data)
    second = entry_at(data, world["a"], MON, p2)
    data = ok(admin.put(f"/api/schedule/entries/{second['id']}", json={"day_of_week": TUE, "period_id": p1["id"]}))
    assert codes(data) == {"TEACHER_UNAVAILABLE", "SUBJECT_HOURS_UNDER"}
    data = ok(place(admin, data, world["a"], world["math"], 3, p3), 201)
    assert "SUBJECT_HOURS_OVER" in codes(data)  # 3 h scheduled, 2 h required


def test_deleting_an_assignment_removes_its_classes(admin, world):
    data = generate(admin)
    data = ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    row = assignment(data, world["a"], world["math"])
    data = ok(admin.delete(f"/api/assignments/{row['id']}"))
    assert data["entries"] == [] and len(data["assignments"]) == 5


# --- combined sections --------------------------------------------------------


def test_combined_sections_are_scheduled_moved_and_counted_as_one_class(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    a, b = assignment(data, world["a"], world["math"]), assignment(data, world["b"], world["math"])
    data = ok(admin.post("/api/assignments/combine", json={"assignment_ids": [a["id"], b["id"]]}))
    a, b = assignment(data, world["a"], world["math"]), assignment(data, world["b"], world["math"])
    assert a["combined_group_id"] == b["combined_group_id"] is not None
    assert b["teacher_id"] == world["ana"]["id"]  # the group shares one teacher
    load = next(x for x in data["teacher_loads"] if x["teacher_id"] == world["ana"]["id"])
    assert load["assigned_hours"] == 2  # counted once, not 4

    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    first, second = entry_at(data, world["a"], MON, p1), entry_at(data, world["b"], MON, p1)
    assert second is not None and first["room_id"] == second["room_id"] is None  # no room holds 80
    assert "TEACHER_DOUBLE_BOOKED" not in codes(data)
    assert next(x for x in data["teacher_loads"] if x["teacher_id"] == world["ana"]["id"])["scheduled_hours"] == 1

    data = ok(admin.put(f"/api/schedule/entries/{first['id']}", json={"room_id": world["room1"]["id"]}))
    assert entry_at(data, world["b"], MON, p1)["room_id"] == world["room1"]["id"]
    assert "ROOM_OVER_CAPACITY" in codes(data)

    data = ok(admin.put(f"/api/schedule/entries/{second['id']}", json={"day_of_week": TUE, "period_id": p2["id"]}))
    assert entry_at(data, world["a"], TUE, p2) and entry_at(data, world["b"], TUE, p2)

    data = assign(admin, data, world["b"], world["math"], world["ben"])
    assert {e["teacher_id"] for e in data["entries"]} == {world["ben"]["id"]}

    data = ok(admin.delete(f"/api/schedule/entries/{first['id']}"))
    assert data["entries"] == []


def test_combining_rules_and_separating(admin, world):
    data = generate(admin)
    a, b = assignment(data, world["a"], world["math"]), assignment(data, world["b"], world["math"])
    other_subject = assignment(data, world["b"], world["sci"])
    mixed = admin.post("/api/assignments/combine", json={"assignment_ids": [a["id"], other_subject["id"]]})
    assert mixed.status_code == 422

    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    blocked = admin.post("/api/assignments/combine", json={"assignment_ids": [a["id"], b["id"]]})
    assert blocked.status_code == 409
    ok(admin.delete("/api/schedule"))

    data = ok(admin.post("/api/assignments/combine", json={"assignment_ids": [a["id"], b["id"]]}))
    data = ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    data = ok(admin.post(f"/api/assignments/{a['id']}/separate"))
    assert {x["combined_group_id"] for x in data["assignments"]} == {None}
    assert {e["combined_group_id"] for e in data["entries"]} == {None} and len(data["entries"]) == 2
    assert admin.post(f"/api/assignments/{a['id']}/separate").status_code == 422


# --- access, audit and export -------------------------------------------------


def test_teacher_role_can_view_but_not_change_the_timetable(admin, world):
    data = generate(admin)
    data = ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    entry = data["entries"][0]
    viewer = add_user(admin, "teacher", "viewer@alpha.example")
    assert len(ok(viewer.get("/api/schedule"))["entries"]) == 1
    assert viewer.get("/api/schedule/export?format=pdf").status_code == 200
    assert viewer.post("/api/schedule/check", json={"entry_id": entry["id"]}).status_code == 200
    row = data["assignments"][0]
    for response in (
        viewer.post("/api/assignments/generate", json={}),
        viewer.put(f"/api/assignments/{row['id']}", json={"teacher_id": None}),
        viewer.delete(f"/api/assignments/{row['id']}"),
        viewer.post("/api/schedule/entries", json={"assignment_id": row["id"], "day_of_week": 2, "period_id": entry["period_id"]}),
        viewer.put(f"/api/schedule/entries/{entry['id']}", json={"pinned": True}),
        viewer.delete(f"/api/schedule/entries/{entry['id']}"),
        viewer.delete("/api/schedule"),
    ):
        assert response.status_code == 403
    scheduler = add_user(admin, "scheduler", "scheduler@alpha.example")
    assert scheduler.put(f"/api/schedule/entries/{entry['id']}", json={"pinned": True}).status_code == 200


def test_another_school_cannot_see_or_touch_the_schedule(admin, world, other_school):
    data = generate(admin)
    data = ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    entry, row = data["entries"][0], data["assignments"][0]
    assert other_school.get("/api/schedule").status_code == 422  # no school year of its own
    assert other_school.get(f"/api/schedule?semester_id={world['semester']['id']}").status_code == 404
    assert other_school.put(f"/api/schedule/entries/{entry['id']}", json={"pinned": True}).status_code == 404
    assert other_school.delete(f"/api/schedule/entries/{entry['id']}").status_code == 404
    assert other_school.get(f"/api/schedule/entries/{entry['id']}/suggestions").status_code == 404
    assert other_school.put(f"/api/assignments/{row['id']}", json={"teacher_id": None}).status_code == 404
    assert other_school.post("/api/schedule/check", json={"assignment_id": row["id"]}).status_code == 404
    own_teacher = other_school.create("/api/teachers", employee_id="X-1", full_name="Other Teacher")
    assert admin.put(f"/api/assignments/{row['id']}", json={"teacher_id": own_teacher["id"]}).status_code == 404


def test_schedule_changes_are_written_to_the_audit_log(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    entry = data["entries"][0]
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"day_of_week": TUE, "period_id": p2["id"]}))
    ok(admin.delete(f"/api/schedule/entries/{entry['id']}"))

    logs = ok(admin.get("/api/audit-logs?entity_type=schedule_entry"))
    assert [log["action"] for log in logs] == ["delete", "move", "create"]
    assert {log["entity_id"] for log in logs} == {entry["id"]} and {log["user_id"] for log in logs} == {admin.user["id"]}
    assert logs[1]["changes"]["summary"] == "11-A · MATH: Mon Period 1 → Tue Period 2"
    assert logs[2]["changes"]["summary"] == "11-A · MATH placed on Mon Period 1 in Room 1"

    both = ok(admin.get("/api/audit-logs?entity_type=schedule_entry,assignment"))
    summaries = [log["changes"]["summary"] for log in both if log["entity_type"] == "assignment"]
    assert "11-A · MATH: teacher none → Ana Cruz" in summaries and "6 subject(s) added from the curriculum" in summaries


def test_export_to_excel_by_section_teacher_and_room(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)

    response = admin.get("/api/schedule/export?view=section&format=xlsx")
    assert response.status_code == 200 and "timetable-by-section.xlsx" in response.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["11-A", "11-B"]
    sheet = workbook["11-A"]
    assert sheet["A1"].value == "Alpha Test School" and "2026-2027, 1st semester" in sheet["A2"].value
    assert [c.value for c in sheet[5]] == ["Period", "Time", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    assert [c.value for c in sheet[6]][:3] == ["Period 1", "07:00-08:00", "MATH\nAna Cruz\nRoom 1"]
    assert sheet["C8"].value == "Break"

    by_teacher = load_workbook(io.BytesIO(admin.get("/api/schedule/export?view=teacher").content))
    assert by_teacher.sheetnames == ["Ana Cruz"]  # teachers without classes are left out
    assert by_teacher["Ana Cruz"]["C6"].value == "MATH\n11-A\nRoom 1"

    one_room = admin.get(f"/api/schedule/export?view=room&id={world['room1']['id']}")
    assert load_workbook(io.BytesIO(one_room.content))["Room 1"]["C6"].value == "MATH\n11-A\nAna Cruz"


def test_export_to_pdf_and_bad_requests(admin, world, other_school):
    data = generate(admin)
    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    response = admin.get("/api/schedule/export?view=section&format=pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF") and len(response.content) > 1500
    assert admin.get("/api/schedule/export?view=students").status_code == 422
    assert admin.get("/api/schedule/export?format=docx").status_code == 422
    assert admin.get("/api/schedule/export?view=teacher&format=pdf").status_code == 404  # nobody teaches yet
    theirs = other_school.create("/api/rooms", code="X", name="Their Room", capacity=30)
    assert admin.get(f"/api/schedule/export?view=room&id={theirs['id']}").status_code == 404


# --- automatic scheduling -----------------------------------------------------


def run_solver(api: Api, **body) -> dict:
    job = ok(api.post("/api/solver/jobs", json={"time_limit": 5, **body}), 202)
    assert job["status"] in ("queued", "running")
    for _ in range(200):
        job = ok(api.get(f"/api/solver/jobs/{job['id']}"))
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("the solver job did not finish")


def loaded(admin: Api, world: dict) -> dict:
    """Every subject has a qualified teacher."""
    data = generate(admin)
    for section in (world["a"], world["b"]):
        data = assign(admin, data, section, world["math"], world["ben"])
        data = assign(admin, data, section, world["sci"], world["ana"])
        data = assign(admin, data, section, world["ict"], world["ana"])
    return data


def test_solver_job_generates_a_timetable_that_is_applied_on_request(admin, world):
    loaded(admin, world)
    job = run_solver(admin)
    result = job["result"]
    assert job["status"] == "done" and result["status"] == "complete"
    assert (result["placed_hours"], result["required_hours"], result["added"]) == (10, 10, 10)
    assert job["progress"]["placed_hours"] == 10 and result["shortages"] == []
    assert "new_entries" not in result and "base" not in result
    assert ok(admin.get("/api/solver/jobs/latest"))["id"] == job["id"]

    assert ok(admin.get("/api/schedule"))["entries"] == []  # nothing saved yet
    data = ok(admin.post(f"/api/solver/jobs/{job['id']}/apply"))
    assert len(data["entries"]) == 10 and data["conflicts"] == []
    assert admin.post(f"/api/solver/jobs/{job['id']}/apply").status_code == 409  # only once
    logs = ok(admin.get("/api/audit-logs?entity_type=solver_job"))
    assert [log["action"] for log in logs] == ["apply", "start"]
    assert logs[0]["changes"]["summary"] == "Generated timetable applied: 10 class(es) placed, 0 replaced, 0 kept"


def test_solver_keeps_pinned_classes_and_fill_mode_keeps_everything(admin, world):
    data = loaded(admin, world)
    p1, p2, p3 = world["periods"]
    data = ok(place(admin, data, world["a"], world["math"], 5, p3), 201)
    data = ok(place(admin, data, world["a"], world["sci"], 5, p2), 201)
    pinned, loose = entry_at(data, world["a"], 5, p3), entry_at(data, world["a"], 5, p2)
    ok(admin.put(f"/api/schedule/entries/{pinned['id']}", json={"pinned": True}))

    job = run_solver(admin, mode="rebuild")
    assert (job["result"]["kept"], job["result"]["removed"], job["result"]["added"]) == (1, 1, 9)
    data = ok(admin.post(f"/api/solver/jobs/{job['id']}/apply"))
    ids = {e["id"] for e in data["entries"]}
    assert pinned["id"] in ids and loose["id"] not in ids and data["conflicts"] == []
    assert entry_at(data, world["a"], 5, p3)["pinned"] is True

    job = run_solver(admin, mode="fill")
    assert (job["result"]["kept"], job["result"]["added"]) == (10, 0)


def test_solver_explains_what_it_could_not_place(admin, world):
    teacher = {**world["ana"], "max_daily_hours": 1, "max_weekly_hours": 2}
    ok(admin.put(f"/api/teachers/{teacher['id']}", json=teacher))
    loaded(admin, world)
    job = run_solver(admin)
    result = job["result"]
    assert result["status"] == "partial" and result["placed_hours"] == 6  # Ben's 4 h plus Ana's 2 h
    assert any("Ana Cruz: Assigned 6 h a week; the weekly limit is 2 h." == p for p in result["problems"])
    assert result["shortages"] and all("could not be placed" in s["message"] for s in result["shortages"])
    assert any("Ana Cruz would pass the" in s["message"] for s in result["shortages"])


def test_stale_result_cannot_be_applied_and_access_is_restricted(admin, world, other_school):
    data = loaded(admin, world)
    job = run_solver(admin)
    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)  # timetable changed meanwhile
    stale = admin.post(f"/api/solver/jobs/{job['id']}/apply")
    assert stale.status_code == 409 and "Run the scheduler again" in stale.json()["detail"]

    viewer = add_user(admin, "teacher", "viewer@alpha.example")
    assert viewer.get(f"/api/solver/jobs/{job['id']}").status_code == 200
    assert viewer.post("/api/solver/jobs", json={}).status_code == 403
    assert viewer.post(f"/api/solver/jobs/{job['id']}/apply").status_code == 403
    assert other_school.get(f"/api/solver/jobs/{job['id']}").status_code == 404
    assert other_school.post(f"/api/solver/jobs/{job['id']}/apply").status_code == 404
    assert admin.post("/api/solver/jobs", json={"mode": "shuffle"}).status_code == 422
    assert admin.post("/api/solver/jobs", json={"time_limit": 9999}).status_code == 422


def test_job_interrupted_by_a_restart_is_reported_as_failed(admin, world):
    from app.db import SessionLocal
    from app.models import SolverJob

    with SessionLocal() as db:
        job = SolverJob(school_id=admin.user["school_id"], semester_id=world["semester"]["id"], status="running", mode="fill", time_limit=5)
        db.add(job)
        db.commit()
        job_id = job.id
    body = ok(admin.get(f"/api/solver/jobs/{job_id}"))
    assert body["status"] == "failed" and "restarted" in body["error"]
    assert admin.post("/api/solver/jobs", json={"time_limit": 5}).status_code == 202  # not blocked by the dead job
    for _ in range(200):
        if ok(admin.get("/api/solver/jobs/latest"))["status"] == "done":
            break
        time.sleep(0.1)


# --- substitution finder ------------------------------------------------------


def test_substitute_finder_lists_who_can_cover_an_absent_teacher(admin, world):
    data = loaded(admin, world)
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["sci"], MON, p1), 201)  # Ana
    data = ok(place(admin, data, world["b"], world["sci"], MON, p2), 201)  # Ana
    data = ok(place(admin, data, world["b"], world["math"], MON, p1), 201)  # Ben, busy in period 1
    cara = admin.create("/api/teachers", employee_id="T-3", full_name="Cara Lim", qualified_subject_ids=[world["sci"]["id"]])

    found = ok(admin.get(f"/api/substitutes?teacher_id={world['ana']['id']}&day_of_week={MON}"))
    first, second = found["classes"]
    assert (first["period_id"], first["section_ids"]) == (p1["id"], [world["a"]["id"]])
    assert [c["teacher_id"] for c in first["candidates"]] == [cara["id"]]  # Ben teaches then
    assert first["candidates"][0] == {
        "teacher_id": cara["id"], "qualified": True, "knows_section": False, "day_hours": 1, "week_hours": 1, "notes": [],
    }
    assert [c["teacher_id"] for c in second["candidates"]] == [cara["id"], world["ben"]["id"]]
    assert second["candidates"][1]["notes"] == ["Not qualified for this subject"]
    assert second["candidates"][1]["knows_section"] is True

    assert ok(admin.get(f"/api/substitutes?teacher_id={world['ana']['id']}&day_of_week={TUE}"))["classes"] == []
    viewer = add_user(admin, "teacher", "viewer@alpha.example")
    assert viewer.get(f"/api/substitutes?teacher_id={world['ana']['id']}&day_of_week={MON}").status_code == 200


# --- remarks and signatories (ideas from the legacy scheduling system) --------


def test_class_remarks_are_saved_shown_and_exported(admin, world):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    p1 = world["periods"][0]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    entry = entry_at(data, world["a"], MON, p1)
    assert entry["remarks"] is None

    data = ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"remarks": "  Bring calculators  "}))
    assert entry_at(data, world["a"], MON, p1)["remarks"] == "Bring calculators"
    sheet = load_workbook(io.BytesIO(admin.get("/api/schedule/export?view=section").content))["11-A"]
    assert sheet["C6"].value == "MATH\nAna Cruz\nRoom 1\nBring calculators"
    log = ok(admin.get("/api/audit-logs?entity_type=schedule_entry"))[0]
    assert log["changes"]["summary"] == "11-A · MATH: remarks: Bring calculators"

    # Moving a class keeps its note; an empty note clears it; too long is refused.
    data = ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"day_of_week": TUE, "period_id": p1["id"]}))
    assert entry_at(data, world["a"], TUE, p1)["remarks"] == "Bring calculators"
    data = ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"remarks": " "}))
    assert entry_at(data, world["a"], TUE, p1)["remarks"] is None
    assert admin.put(f"/api/schedule/entries/{entry['id']}", json={"remarks": "x" * 121}).status_code == 422


def test_signatories_are_validated_and_printed_under_exports(admin, world):
    people = [
        {"label": "Prepared by", "name": " Maria Santos ", "position": "Class Program Coordinator"},
        {"label": "Approved", "name": "Jose Reyes", "position": "School Principal"},
    ]
    school = ok(admin.put("/api/school", json={"name": "Alpha Test School", "settings": {"signatories": people}}))
    assert school["settings"]["signatories"][0] == {
        "label": "Prepared by", "name": "Maria Santos", "position": "Class Program Coordinator",
    }
    assert school["settings"]["default_max_daily_hours"] == 6  # other settings untouched

    for bad in ([{"label": "Approved", "name": ""}], "nobody", [{"label": "x", "name": "y"}] * 7):
        response = admin.put("/api/school", json={"name": "Alpha Test School", "settings": {"signatories": bad}})
        assert response.status_code == 422

    data = generate(admin)
    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    sheet = load_workbook(io.BytesIO(admin.get("/api/schedule/export?view=section").content))["11-A"]
    cells = {cell.value: cell.coordinate for row in sheet.iter_rows() for cell in row if cell.value}
    assert {"Prepared by:", "Maria Santos", "Class Program Coordinator", "Approved:", "Jose Reyes", "School Principal"} <= set(cells)
    assert cells["Prepared by:"] == "A11" and cells["Approved:"] == "C11" and cells["Jose Reyes"] == "C14"

    with_signatures = admin.get("/api/schedule/export?view=section&format=pdf")
    assert with_signatures.status_code == 200 and with_signatures.content.startswith(b"%PDF")
    ok(admin.put("/api/school", json={"name": "Alpha Test School", "settings": {"signatories": []}}))
    without = admin.get("/api/schedule/export?view=section&format=pdf")
    assert len(with_signatures.content) > len(without.content)


def test_auto_assign_fills_only_subjects_without_a_teacher(admin, world):
    admin.create("/api/teachers", employee_id="T-9", full_name="Away Teacher", is_active=False, qualified_subject_ids=[world["ict"]["id"]])
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ben"])  # chosen by hand: kept
    p1 = world["periods"][0]
    data = ok(place(admin, data, world["b"], world["sci"], MON, p1), 201)  # placed before it had a teacher

    data = ok(admin.post("/api/assignments/auto-assign", json={}))
    assert (data["assigned"], data["left"]) == (5, 0)
    teacher = {(a["section_id"], a["subject_id"]): a["teacher_id"] for a in data["assignments"]}
    assert teacher[(world["a"]["id"], world["math"]["id"])] == world["ben"]["id"]
    assert teacher[(world["a"]["id"], world["ict"]["id"])] == world["ana"]["id"]  # never the inactive teacher
    assert entry_at(data, world["b"], MON, p1)["teacher_id"] == world["ana"]["id"]
    assert all(load["status"] != "over" for load in data["teacher_loads"])
    log = ok(admin.get("/api/audit-logs?entity_type=assignment"))[0]
    assert log["changes"]["summary"] == "Teachers assigned automatically to 5 subject(s); 0 still without a teacher"

    assert ok(admin.post("/api/assignments/auto-assign", json={}))["assigned"] == 0
    viewer = add_user(admin, "teacher", "viewer@alpha.example")
    assert viewer.post("/api/assignments/auto-assign", json={}).status_code == 403
