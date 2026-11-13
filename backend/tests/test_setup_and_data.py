import io

from openpyxl import Workbook

from .conftest import BELL, SCHOOL_YEAR

SUBJECT = {"code": "MATH1", "name": "General Mathematics", "type": "core", "hours_per_week": 4}


def csv_file(text: str, name: str = "data.csv") -> dict:
    return {"file": (name, text.encode("utf-8"), "text/csv")}


def xlsx_file(rows: list[list]) -> dict:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return {"file": ("data.xlsx", buffer.getvalue(), "application/octet-stream")}


# --- onboarding -------------------------------------------------------------


def test_onboarding_cannot_complete_until_every_step_is_done(admin):
    assert admin.get("/api/onboarding/status").json() == {
        "completed": False,
        "steps": {"school_year": False, "shifts": False, "periods": False},
    }
    assert admin.post("/api/onboarding/complete").status_code == 422

    admin.create("/api/school-years", **SCHOOL_YEAR)
    shift = admin.create("/api/shifts", name="Morning", start_time="07:00", end_time="12:00")
    blocked = admin.post("/api/onboarding/complete")
    assert blocked.status_code == 422 and "periods" in blocked.json()["detail"]

    assert admin.put(f"/api/shifts/{shift['id']}/periods", json=BELL).status_code == 200
    assert admin.post("/api/onboarding/complete").json()["onboarding_completed"] is True
    assert admin.get("/api/onboarding/status").json()["completed"] is True


def test_school_profile_update_merges_settings(admin):
    response = admin.put(
        "/api/school",
        json={"name": "Alpha Test School", "division": "Sample Division", "settings": {"default_max_weekly_hours": 28}},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["division"] == "Sample Division"
    assert body["settings"]["default_max_weekly_hours"] == 28
    assert body["settings"]["default_max_daily_hours"] == 6  # untouched default survives


def test_school_year_is_created_with_two_semesters(admin):
    year = admin.create("/api/school-years", **SCHOOL_YEAR)
    assert [s["number"] for s in year["semesters"]] == [1, 2]
    assert [s["is_active"] for s in year["semesters"]] == [True, False]


def test_school_year_validates_dates(admin):
    overlap = {**SCHOOL_YEAR, "second_semester": {"start_date": "2026-10-01", "end_date": "2027-03-31"}}
    assert admin.post("/api/school-years", json=overlap).status_code == 422
    outside = {**SCHOOL_YEAR, "first_semester": {"start_date": "2026-05-01", "end_date": "2026-10-30"}}
    assert admin.post("/api/school-years", json=outside).status_code == 422
    assert admin.post("/api/school-years", json={**SCHOOL_YEAR, "end_date": "2026-01-01"}).status_code == 422


def test_only_one_school_year_and_semester_is_active(admin):
    first = admin.create("/api/school-years", **SCHOOL_YEAR)
    later = {
        "name": "2027-2028",
        "start_date": "2027-06-14",
        "end_date": "2028-03-31",
        "first_semester": {"start_date": "2027-06-14", "end_date": "2027-10-29"},
        "second_semester": {"start_date": "2027-11-08", "end_date": "2028-03-31"},
    }
    second = admin.create("/api/school-years", **later)
    years = {y["id"]: y for y in admin.get("/api/school-years").json()}
    assert years[first["id"]]["is_active"] is False
    assert years[second["id"]]["is_active"] is True

    sem2 = second["semesters"][1]
    body = {"start_date": sem2["start_date"], "end_date": sem2["end_date"], "is_active": True}
    assert admin.put(f"/api/semesters/{sem2['id']}", json=body).status_code == 200
    active = [s for y in admin.get("/api/school-years").json() for s in y["semesters"] if s["is_active"]]
    assert [s["id"] for s in active] == [sem2["id"]]


def test_bell_schedule_rejects_overlaps_and_periods_outside_the_shift(admin):
    shift = admin.create("/api/shifts", name="Morning", start_time="07:00", end_time="12:00")
    url = f"/api/shifts/{shift['id']}/periods"
    overlapping = [BELL[0], {"name": "Clash", "start_time": "07:30", "end_time": "08:30"}]
    assert admin.put(url, json=overlapping).status_code == 422
    too_early = [{"name": "Early", "start_time": "06:00", "end_time": "07:00"}]
    assert admin.put(url, json=too_early).status_code == 422
    too_late = [{"name": "Late", "start_time": "11:30", "end_time": "12:30"}]
    assert admin.put(url, json=too_late).status_code == 422
    backwards = [{"name": "Backwards", "start_time": "09:00", "end_time": "08:00"}]
    assert admin.put(url, json=backwards).status_code == 422


def test_editing_bell_schedule_keeps_period_ids_stable(school_setup, admin):
    shift = school_setup["shift"]
    ids = [p["id"] for p in shift["periods"]]
    assert [p["is_break"] for p in shift["periods"]] == [False, False, True, False]

    renamed = [{**BELL[0], "name": "First"}, BELL[1], BELL[2]]
    updated = admin.put(f"/api/shifts/{shift['id']}/periods", json=renamed).json()
    assert [p["id"] for p in updated["periods"]] == ids[:3]
    assert updated["periods"][0]["name"] == "First"


# --- CRUD -------------------------------------------------------------------


def test_subject_crud_and_validation(admin):
    subject = admin.create("/api/subjects", **SUBJECT, required_room_type="computer_lab")
    assert subject["hours_per_week"] == 4 and subject["required_room_type"] == "computer_lab"

    updated = admin.put(f"/api/subjects/{subject['id']}", json={**SUBJECT, "hours_per_week": 2.5, "is_heavy": True})
    assert updated.json()["hours_per_week"] == 2.5 and updated.json()["is_heavy"] is True

    assert admin.post("/api/subjects", json={**SUBJECT, "code": "A", "hours_per_week": 0}).status_code == 422
    assert admin.post("/api/subjects", json={**SUBJECT, "code": "B", "type": "elective"}).status_code == 422
    assert admin.post("/api/subjects", json={**SUBJECT, "code": "C", "required_room_type": "pool"}).status_code == 422
    assert admin.post("/api/subjects", json=SUBJECT).status_code == 409  # duplicate code

    assert admin.delete(f"/api/subjects/{subject['id']}").status_code == 204
    assert admin.get(f"/api/subjects/{subject['id']}").status_code == 404


def test_room_requires_positive_capacity_and_known_type(admin):
    assert admin.create("/api/rooms", code="R1", name="Room 1", capacity=40)["type"] == "lecture"
    assert admin.post("/api/rooms", json={"code": "R2", "name": "Room 2", "capacity": 0}).status_code == 422
    assert admin.post("/api/rooms", json={"code": "R3", "name": "Room 3", "capacity": 30, "type": "attic"}).status_code == 422


def test_track_in_use_cannot_be_deleted(school_setup, admin):
    response = admin.delete(f"/api/tracks/{school_setup['track']['id']}")
    assert response.status_code == 409
    assert admin.get(f"/api/tracks/{school_setup['track']['id']}").status_code == 200


def test_teacher_gets_school_default_load_limits(admin):
    admin.put("/api/school", json={"name": "Alpha Test School", "settings": {"default_max_weekly_hours": 28}})
    teacher = admin.create("/api/teachers", employee_id="T-1", full_name="Sample Teacher")
    assert (teacher["max_daily_hours"], teacher["max_weekly_hours"]) == (6, 28)

    custom = admin.create("/api/teachers", employee_id="T-2", full_name="Other Teacher", max_daily_hours=4, max_weekly_hours=20)
    assert (custom["max_daily_hours"], custom["max_weekly_hours"]) == (4, 20)

    bad = {"employee_id": "T-3", "full_name": "Bad Limits", "max_daily_hours": 8, "max_weekly_hours": 5}
    assert admin.post("/api/teachers", json=bad).status_code == 422


def test_teacher_qualifications_and_availability(school_setup, admin):
    math = admin.create("/api/subjects", **SUBJECT)
    stat = admin.create("/api/subjects", **{**SUBJECT, "code": "STAT1", "name": "Statistics"})
    p1, p2, recess, _ = school_setup["shift"]["periods"]

    data = {
        "employee_id": "T-1",
        "full_name": "Sample Teacher",
        "qualified_subject_ids": [math["id"], stat["id"]],
        "availability": [
            {"day_of_week": 1, "period_id": p1["id"], "kind": "unavailable"},
            {"day_of_week": 2, "period_id": p2["id"], "kind": "preferred"},
        ],
    }
    teacher = admin.create("/api/teachers", **data)
    assert teacher["qualified_subject_ids"] == sorted([math["id"], stat["id"]])
    assert len(teacher["availability"]) == 2

    # Replacing the lists on update, including re-using the same slot.
    data["qualified_subject_ids"] = [stat["id"]]
    data["availability"] = [{"day_of_week": 1, "period_id": p1["id"], "kind": "preferred"}]
    updated = admin.put(f"/api/teachers/{teacher['id']}", json=data).json()
    assert updated["qualified_subject_ids"] == [stat["id"]]
    assert updated["availability"] == [{"day_of_week": 1, "period_id": p1["id"], "kind": "preferred"}]

    on_break = {**data, "availability": [{"day_of_week": 1, "period_id": recess["id"], "kind": "unavailable"}]}
    assert admin.put(f"/api/teachers/{teacher['id']}", json=on_break).status_code == 422
    twice = {**data, "availability": data["availability"] * 2}
    assert admin.put(f"/api/teachers/{teacher['id']}", json=twice).status_code == 422
    sunday = {**data, "availability": [{"day_of_week": 7, "period_id": p1["id"], "kind": "unavailable"}]}
    assert admin.put(f"/api/teachers/{teacher['id']}", json=sunday).status_code == 422
    unknown_subject = {**data, "qualified_subject_ids": [999999]}
    assert admin.put(f"/api/teachers/{teacher['id']}", json=unknown_subject).status_code == 422


def test_section_defaults_to_active_school_year_and_validates(school_setup, admin):
    base = {
        "name": "11-STEM-A",
        "strand_id": school_setup["strand"]["id"],
        "grade_level": 11,
        "shift_id": school_setup["shift"]["id"],
        "student_count": 40,
    }
    section = admin.create("/api/sections", **base)
    assert section["school_year_id"] == school_setup["year"]["id"]

    assert admin.post("/api/sections", json=base).status_code == 409  # same name, same year
    assert admin.post("/api/sections", json={**base, "name": "G10", "grade_level": 10}).status_code == 422
    assert admin.post("/api/sections", json={**base, "name": "Neg", "student_count": -1}).status_code == 422
    assert admin.post("/api/sections", json={**base, "name": "NoStrand", "strand_id": 999999}).status_code == 422

    listed = admin.get("/api/sections", params={"strand_id": school_setup["strand"]["id"]}).json()
    assert [s["name"] for s in listed] == ["11-STEM-A"]


def test_section_needs_a_school_year(admin):
    track = admin.create("/api/tracks", code="ACAD", name="Academic Track")
    strand = admin.create("/api/strands", track_id=track["id"], code="STEM", name="STEM")
    shift = admin.create("/api/shifts", name="Morning", start_time="07:00", end_time="12:00")
    body = {"name": "11-A", "strand_id": strand["id"], "grade_level": 11, "shift_id": shift["id"]}
    response = admin.post("/api/sections", json=body)
    assert response.status_code == 422 and "school year" in response.json()["detail"]


# --- seed template ----------------------------------------------------------


def test_template_lists_all_deped_tracks(admin):
    template = admin.get("/api/templates/shs").json()
    strands = {s["code"] for t in template["tracks"] for s in t["strands"]}
    assert strands == {"ABM", "HUMSS", "STEM", "GAS", "ICT", "HE", "IA", "AFA", "SPORTS", "AD"}


def test_applying_template_is_idempotent_and_keeps_local_edits(admin):
    first = admin.post("/api/templates/shs/apply", json={"strand_codes": ["STEM", "ict"]}).json()
    assert first["tracks"] == 2 and first["strands"] == 2 and first["subjects"] > 20

    subjects = {s["code"]: s for s in admin.get("/api/subjects").json()}
    # STEM swaps Earth and Life Science for Earth Science; ICT keeps the common core.
    stem = next(s for s in admin.get("/api/strands").json() if s["code"] == "STEM")
    stem_subject_ids = {e["subject_id"] for e in admin.get("/api/curriculum", params={"strand_id": stem["id"]}).json()}
    assert subjects["CORE-EARTHSCI"]["id"] in stem_subject_ids
    assert subjects["CORE-ELS"]["id"] not in stem_subject_ids
    edited = {**subjects["CORE-GENMATH"], "hours_per_week": 5}
    admin.put(f"/api/subjects/{edited['id']}", json=edited)

    again = admin.post("/api/templates/shs/apply", json={"strand_codes": ["STEM"]}).json()
    assert again == {"tracks": 0, "strands": 0, "subjects": 0, "curriculum_entries": 0}
    assert admin.get(f"/api/subjects/{edited['id']}").json()["hours_per_week"] == 5

    assert admin.post("/api/templates/shs/apply", json={"strand_codes": ["NOPE"]}).status_code == 422


def test_template_curriculum_is_per_strand_grade_and_semester(admin):
    admin.post("/api/templates/shs/apply", json={"strand_codes": ["ABM"]})
    strand = admin.get("/api/strands").json()[0]
    entries = admin.get("/api/curriculum", params={"strand_id": strand["id"], "grade_level": 11, "semester_number": 1}).json()
    codes = {s["id"]: s["code"] for s in admin.get("/api/subjects").json()}
    assert {"CORE-GENMATH", "ABM-BMATH"} <= {codes[e["subject_id"]] for e in entries}
    assert all(e["grade_level"] == 11 and e["semester_number"] == 1 for e in entries)


# --- CSV / Excel import -----------------------------------------------------


def test_csv_import_creates_updates_and_reports_bad_rows(admin):
    text = (
        "code,name,type,hours_per_week,required_room_type,is_heavy\n"
        "MATH1,General Mathematics,core,4,lecture,yes\n"
        "ICT1,Programming,Specialized,8,Computer Lab,no\n"
        "BAD1,Broken Subject,elective,4,lecture,no\n"
        "BAD2,No Hours,core,,lecture,no\n"
        "MATH1,Duplicate,core,4,lecture,no\n"
    )
    result = admin.post("/api/import/subjects", files=csv_file(text)).json()
    assert (result["created"], result["updated"]) == (2, 0)
    assert [e["row"] for e in result["errors"]] == [4, 5, 6]
    assert "hours_per_week" in result["errors"][1]["message"]
    assert "duplicate" in result["errors"][2]["message"]

    subjects = {s["code"]: s for s in admin.get("/api/subjects").json()}
    assert set(subjects) == {"MATH1", "ICT1"}
    assert subjects["ICT1"]["required_room_type"] == "computer_lab" and subjects["MATH1"]["is_heavy"] is True

    again = admin.post("/api/import/subjects", files=csv_file("code,name,type,hours_per_week\nmath1,Gen Math,core,5\n")).json()
    assert (again["created"], again["updated"], again["errors"]) == (0, 1, [])
    assert {s["code"]: s["hours_per_week"] for s in admin.get("/api/subjects").json()}["MATH1"] == 5


def test_import_dry_run_changes_nothing(admin):
    text = "code,capacity,name,type\nR101,45,Room 101,lecture\nGYM,120,Court,gym\n"
    result = admin.post("/api/import/rooms", params={"dry_run": True}, files=csv_file(text)).json()
    assert result == {"dry_run": True, "created": 2, "updated": 0, "errors": []}
    assert admin.get("/api/rooms").json() == []
    assert admin.post("/api/import/rooms", files=csv_file(text)).json()["created"] == 2
    assert len(admin.get("/api/rooms").json()) == 2


def test_excel_import_of_teachers_links_qualified_subjects(admin):
    admin.create("/api/subjects", **SUBJECT)
    admin.create("/api/subjects", **{**SUBJECT, "code": "STAT1", "name": "Statistics"})
    rows = [
        ["Employee ID", "Full Name", "Max Daily Hours", "Max Weekly Hours", "Qualified Subjects"],
        ["T-0001", "Sample Teacher One", 6, 30, "MATH1; STAT1"],
        [1002, "Sample Teacher Two", None, None, None],
        ["T-0003", "Sample Teacher Three", 6, 30, "MATH1;GHOST"],
    ]
    result = admin.post("/api/import/teachers", files=xlsx_file(rows)).json()
    assert (result["created"], result["updated"]) == (2, 0)
    assert result["errors"] == [{"row": 4, "message": "Subject 'GHOST' was not found"}]

    teachers = {t["employee_id"]: t for t in admin.get("/api/teachers").json()}
    assert len(teachers["T-0001"]["qualified_subject_ids"]) == 2
    assert teachers["1002"]["max_weekly_hours"] == 30  # school default applied


def test_import_sections_and_strands_resolve_codes(school_setup, admin):
    strands = "track_code,code,name\nACAD,ABM,Accountancy Business and Management\nNOPE,XYZ,Unknown Track\n"
    result = admin.post("/api/import/strands", files=csv_file(strands)).json()
    assert result["created"] == 1 and result["errors"][0]["message"] == "Track 'NOPE' was not found"

    admin.create("/api/teachers", employee_id="T-1", full_name="Sample Adviser")
    sections = (
        "name,strand_code,grade_level,shift_name,adviser_employee_id,student_count\n"
        "11-STEM-A,stem,11,morning,T-1,40\n"
        "12-ABM-A,ABM,12,Morning,,35\n"
        "11-X,STEM,9,Morning,,30\n"
        "11-Y,STEM,11,Night,,30\n"
    )
    result = admin.post("/api/import/sections", files=csv_file(sections)).json()
    assert result["created"] == 2 and [e["row"] for e in result["errors"]] == [4, 5], result
    by_name = {s["name"]: s for s in admin.get("/api/sections").json()}
    assert by_name["11-STEM-A"]["adviser_id"] is not None and by_name["12-ABM-A"]["student_count"] == 35


def test_import_rejects_bad_files(admin, teacher_user):
    assert admin.post("/api/import/subjects", files=csv_file("code,name\nA,B\n")).status_code == 400  # missing columns
    assert admin.post("/api/import/subjects", files=csv_file("", name="x.csv")).status_code == 400
    assert admin.post("/api/import/subjects", files=csv_file("a,b", name="x.pdf")).status_code == 400
    assert admin.post("/api/import/nothing", files=csv_file("a,b")).status_code == 404
    assert teacher_user.post("/api/import/rooms", files=csv_file("code,capacity\nR1,40\n")).status_code == 403


def test_import_template_download(admin):
    response = admin.get("/api/import/teachers/template")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    assert response.text.lstrip("﻿").splitlines()[0] == (
        "employee_id,full_name,max_daily_hours,max_weekly_hours,qualified_subjects"
    )


def test_hosted_database_connection_string_is_used_as_given():
    from app.config import Settings

    hosted = Settings(jwt_secret="x", DATABASE_URL="postgresql://app:secret@ep-quiet-1.ap-southeast-1.aws.neon.tech/shs?sslmode=require")
    url = hosted.database_url
    assert (url.drivername, url.host, url.username, url.database) == ("postgresql+psycopg", "ep-quiet-1.ap-southeast-1.aws.neon.tech", "app", "shs")
    assert url.query["sslmode"] == "require"
    local = Settings(jwt_secret="x", DATABASE_URL="", POSTGRES_DB="local_db")
    assert (local.database_url.host, local.database_url.database) == ("localhost", "local_db")
