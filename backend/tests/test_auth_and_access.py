from sqlalchemy import select

from app.db import SessionLocal
from app.models import Base, User

from .conftest import PASSWORD, add_user, register

SUBJECT = {"code": "MATH1", "name": "General Mathematics", "type": "core", "hours_per_week": 4}


# --- authentication ---------------------------------------------------------


def test_register_creates_school_and_admin(client):
    admin = register(client)
    assert admin.user["role"] == "admin"
    assert admin.get("/api/auth/me").json()["email"] == "admin@alpha.example"
    school = admin.get("/api/school").json()
    assert school["name"] == "Alpha Test School"
    assert school["onboarding_completed"] is False
    assert school["settings"]["default_max_daily_hours"] == 6


def test_password_is_stored_as_argon2_hash(client):
    register(client)
    with SessionLocal() as db:
        stored = db.scalar(select(User.password_hash))
    assert stored.startswith("$argon2")
    assert PASSWORD not in stored


def test_login_success_and_failure_use_same_message(client, admin):
    ok = client.post("/api/auth/login", json={"email": "ADMIN@alpha.example ", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["access_token"]
    wrong = client.post("/api/auth/login", json={"email": "admin@alpha.example", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@alpha.example", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_register_rejects_weak_password_bad_email_and_duplicates(client, admin):
    base = {"school_name": "Gamma School", "full_name": "Someone", "email": "x@gamma.example", "password": PASSWORD}
    assert client.post("/api/auth/register", json={**base, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "email": "admin@alpha.example"}).status_code == 409


def test_requests_without_valid_token_are_rejected(client):
    assert client.get("/api/subjects").status_code == 401
    assert client.get("/api/subjects", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_deactivated_user_loses_access_immediately(admin, scheduler):
    assert scheduler.get("/api/subjects").status_code == 200
    assert admin.put(f"/api/users/{scheduler.user['id']}", json={"is_active": False}).status_code == 200
    assert scheduler.get("/api/subjects").status_code == 401


# --- roles ------------------------------------------------------------------


def test_teacher_role_is_read_only(admin, teacher_user):
    subject = admin.create("/api/subjects", **SUBJECT)
    assert teacher_user.get("/api/subjects").status_code == 200
    assert teacher_user.post("/api/subjects", json={**SUBJECT, "code": "X"}).status_code == 403
    assert teacher_user.put(f"/api/subjects/{subject['id']}", json=SUBJECT).status_code == 403
    assert teacher_user.delete(f"/api/subjects/{subject['id']}").status_code == 403
    assert teacher_user.post("/api/shifts", json={"name": "S", "start_time": "07:00", "end_time": "08:00"}).status_code == 403
    assert teacher_user.post("/api/templates/shs/apply", json={"strand_codes": ["STEM"]}).status_code == 403


def test_scheduler_can_edit_data_but_not_admin_areas(admin, scheduler):
    assert scheduler.post("/api/subjects", json=SUBJECT).status_code == 201
    assert scheduler.get("/api/users").status_code == 403
    assert scheduler.get("/api/audit-logs").status_code == 403
    assert scheduler.put("/api/school", json={"name": "Renamed"}).status_code == 403
    assert scheduler.post("/api/onboarding/complete").status_code == 403
    new_user = {"email": "n@alpha.example", "full_name": "New User", "password": PASSWORD, "role": "admin"}
    assert scheduler.post("/api/users", json=new_user).status_code == 403


def test_admin_cannot_lock_themselves_out(admin):
    me = admin.user["id"]
    assert admin.put(f"/api/users/{me}", json={"role": "teacher"}).status_code == 422
    assert admin.put(f"/api/users/{me}", json={"is_active": False}).status_code == 422
    assert admin.delete(f"/api/users/{me}").status_code == 422


# --- tenant isolation -------------------------------------------------------


def test_schools_cannot_see_or_change_each_others_records(admin, other_school):
    subject = admin.create("/api/subjects", **SUBJECT)
    url = f"/api/subjects/{subject['id']}"
    assert other_school.get("/api/subjects").json() == []
    assert other_school.get(url).status_code == 404
    assert other_school.put(url, json=SUBJECT).status_code == 404
    assert other_school.delete(url).status_code == 404
    assert admin.get(url).status_code == 200


def test_records_cannot_reference_another_schools_rows(admin, other_school):
    track = admin.create("/api/tracks", code="ACAD", name="Academic Track")
    response = other_school.post("/api/strands", json={"track_id": track["id"], "code": "STEM", "name": "STEM"})
    assert response.status_code == 422

    subject = admin.create("/api/subjects", **SUBJECT)
    teacher = {"employee_id": "T-1", "full_name": "Other Teacher", "qualified_subject_ids": [subject["id"]]}
    assert other_school.post("/api/teachers", json=teacher).status_code == 422


def test_same_codes_are_allowed_in_different_schools(admin, other_school):
    admin.create("/api/subjects", **SUBJECT)
    other_school.create("/api/subjects", **SUBJECT)
    assert admin.post("/api/subjects", json=SUBJECT).status_code == 409


def test_users_and_audit_logs_are_scoped_to_the_school(admin, other_school):
    add_user(admin, "scheduler", "s@alpha.example")
    assert [u["email"] for u in other_school.get("/api/users").json()] == ["admin@beta.example"]
    assert all(log["entity_type"] != "user" for log in other_school.get("/api/audit-logs").json())


# --- audit log & privacy ----------------------------------------------------


def test_changes_are_audited_without_passwords(admin):
    subject = admin.create("/api/subjects", **SUBJECT)
    admin.put(f"/api/subjects/{subject['id']}", json={**SUBJECT, "hours_per_week": 5})
    admin.delete(f"/api/subjects/{subject['id']}")
    add_user(admin, "scheduler", "s@alpha.example")

    logs = admin.get("/api/audit-logs").json()
    subject_actions = [log["action"] for log in logs if log["entity_type"] == "subject"]
    assert sorted(subject_actions) == ["create", "delete", "update"]
    assert all(log["user_id"] == admin.user["id"] for log in logs)
    assert PASSWORD not in str(logs)
    assert "password" not in next(log for log in logs if log["entity_type"] == "user")["changes"]


def test_schema_holds_no_student_personal_data():
    """RA 10173 data minimisation: only a head count per section is stored."""
    assert "students" not in Base.metadata.tables
    student_columns = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if "student" in column.name
    ]
    assert student_columns == ["sections.student_count"]
    assert {c.name for c in Base.metadata.tables["teachers"].columns} == {
        "id", "school_id", "employee_id", "full_name", "max_daily_hours", "max_weekly_hours", "is_active",
    }
